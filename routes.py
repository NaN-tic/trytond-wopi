import datetime as dt
import json
import mimetypes
import os
from html import escape
from urllib.parse import quote, urlsplit

from werkzeug.exceptions import abort
from werkzeug.wrappers import Response

from trytond.model import fields
from trytond.model.exceptions import AccessError
from trytond.protocols.wrappers import HTTPStatus, with_pool, with_transaction
from trytond.pyson import PYSONDecoder, PYSONEncoder
from trytond.transaction import Transaction, check_access
from trytond.wsgi import app

from . import wopi_token
from .editor import (
    OfficeDiscoveryError, get_office_config_int, get_office_discovery,
    get_office_url, get_wopi_url)
from .wopi_proof import validate as validate_wopi_proof

LOCK_SECONDS = 30 * 60


def _binary_field(pool, model_name, field_name):
    try:
        Model = pool.get(model_name)
        field = Model._fields[field_name]
    except (KeyError, AttributeError):
        abort(404)
    if not isinstance(field, fields.Binary):
        abort(404)
    return Model, field


def _safe_name(name, field):
    name = (name or field).replace('/', '_').replace('\\', '_').strip()
    return name[:255] or field


def _rename_field(Model, binary):
    name = binary.filename
    if not name or name not in Model._fields:
        return None
    return name


def _requested_name(request, current_name):
    name = request.headers.get('X-WOPI-RequestedName', '').strip()
    if (not name or len(name) > 255 or '/' in name or '\\' in name
            or any(ord(char) < 32 for char in name)):
        return None
    # WOPI specifies a name without an extension.  Retain the extension stored
    # by Tryton; accepting one from a client would silently change file type.
    stem = os.path.splitext(name)[0]
    if not stem:
        return None
    return stem + os.path.splitext(current_name or '')[1], stem


def _writable(pool, model_name, field_name, record, field):
    """Test the same model, field and record rules as a normal write."""
    if field.readonly:
        return False
    readonly = field.states.get('readonly')
    if readonly:
        values = record.__class__.read(
            [record.id], list(field.edition_depends | {'id'}))[0]
        values['context'] = Transaction().context
        if PYSONDecoder(values).decode(PYSONEncoder().encode(readonly)):
            return False
    ModelAccess = pool.get('ir.model.access')
    FieldAccess = pool.get('ir.model.field.access')
    if not ModelAccess.check(model_name, 'write', raise_exception=False):
        return False
    if not FieldAccess.check(
            model_name, [field_name], 'write', raise_exception=False):
        return False
    try:
        # read with the current user makes record rules explicit before a
        # capability is minted.  Writes are checked again on every callback.
        record.__class__.read([record.id], [field_name])
    except AccessError:
        return False
    return True


def _claim_record(pool, claim, write=False):
    Model, field = _binary_field(pool, claim['model'], claim['field'])
    if write and (not claim['writable'] or field.readonly):
        abort(403)
    try:
        with Transaction().set_user(claim['user']), check_access():
            record = Model(claim['record'])
            Model.read([record.id], [claim['field']])
            if write and not _writable(
                    pool, claim['model'], claim['field'], record, field):
                abort(403)
    except AccessError:
        # Do not disclose the existence of a record the user can no longer see.
        abort(404)
    return Model, field, record


def _version(record):
    return _last_modified(record) or str(record.id)


def _last_modified(record):
    value = getattr(record, 'write_date', None) or getattr(
        record, 'create_date', None)
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.isoformat().replace('+00:00', 'Z')


def _response(data=b'', status=200, **headers):
    response = Response(data, status=status)
    for name, value in headers.items():
        response.headers[name.replace('_', '-')] = str(value)
    return response


def _json_response(data, status=200, **headers):
    response = _response(
        json.dumps(data, separators=(',', ':')), status, **headers)
    response.content_type = 'application/json'
    return response


def _current_lock(Lock, file_id):
    locks = Lock.search([('file_id', '=', file_id)], limit=1)
    if not locks:
        return None
    lock, = locks
    if lock.expires_at <= dt.datetime.utcnow():
        Lock.delete([lock])
        return None
    return lock


def _lock_conflict(lock):
    return _response(status=409, X_WOPI_Lock=lock.value if lock else '',
        X_WOPI_LockFailureReason='Lock mismatch')


def _lock_value(request):
    value = request.headers.get('X-WOPI-Lock')
    if not value or len(value) > 1024 or not value.isascii():
        abort(400)
    return value


def _editor_action_url(office_url, name, wopi_src):
    try:
        discovery = get_office_discovery(
            office_url, get_office_config_int('discovery_timeout', default=10))
    except OfficeDiscoveryError:
        abort(HTTPStatus.SERVICE_UNAVAILABLE)

    extension = os.path.splitext(name)[1].lower().lstrip('.')
    action_url = next((action.get('urlsrc') for action in discovery.iter('action')
            if action.get('name') == 'edit'
            and action.get('ext', '').lower() == extension), None)
    if not action_url:
        abort(HTTPStatus.NOT_IMPLEMENTED)

    configured = urlsplit(office_url)
    action = urlsplit(action_url)
    if (action.scheme, action.netloc) != (
            configured.scheme, configured.netloc):
        abort(HTTPStatus.BAD_GATEWAY)
    wopi_src = quote(wopi_src, safe='')
    if '{{WOPISrc}}' in action_url:
        return action_url.replace('{{WOPISrc}}', wopi_src)
    # Current Collabora discovery documents publish a URL ending in '?' and
    # require the WOPI host to append this query parameter itself.
    if action_url.endswith(('?', '&')):
        return action_url + 'WOPISrc=' + wopi_src
    return action_url + ('&' if '?' in action_url else '?') + 'WOPISrc=' + wopi_src


def _editor_form(action_url, access_token):
    """POST the WOPI token to the configured office server in an iframe."""
    return Response('''<!doctype html>
<html><head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<meta name="viewport" content="width=device-width">
<style>
body { margin: 0; padding: 0; overflow: hidden; }
.office_frame { width: 100%%; height: 100%%; position: absolute;
 top: 0; left: 0; right: 0; bottom: 0; margin: 0; border: 0; display: block; }
</style></head><body>
<form id="office_form" name="office_form" target="office_frame"
 action="%s" enctype="multipart/form-data" method="post">
<input type="hidden" name="access_token" value="%s">
<input type="hidden" name="access_token_ttl" value="0">
</form>
<iframe name="office_frame" id="office_frame" class="office_frame"
 title="Office Frame"
 allowfullscreen="true"
 sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-top-navigation allow-popups-to-escape-sandbox allow-downloads allow-modals"
 allow="autoplay; camera; microphone; display-capture"></iframe>
<script>document.getElementById('office_form').submit();</script>
</body></html>''' % (
                escape(action_url, quote=True), escape(access_token, quote=True)),
        content_type='text/html')


def _wopi_claim(request, pool, file_id):
    access_token = request.args.get('access_token', '')
    claim = wopi_token.check(request.view_args['database_name'], file_id,
        access_token)
    validate_wopi_proof(request, access_token)
    Lease = pool.get('wopi.lease')
    if not Lease.renew(access_token):
        abort(401)
    return claim


@app.route('/<database_name>/wopi/open/<string:model>/<int:record>/<field>',
    methods={'GET'})
@app.route('/<database_name>/collabora/open/<string:model>/<int:record>/<field>',
    methods={'GET'})
@app.auth_required
@with_pool
@with_transaction(
    readonly=False, user='request', context={'_check_access': True})
def open_editor(request, pool, model, record, field):
    Model, binary = _binary_field(pool, model, field)
    try:
        current = Model(record)
        Model.read([record], [field])
    except AccessError:
        abort(404)
    writable = _writable(pool, model, field, current, binary)
    name = _safe_name(request.args.get('name'), field)
    file_id, access_token = wopi_token.make(
        Transaction().database.name, Transaction().user, model, record, field,
        writable, name)
    Lease = pool.get('wopi.lease')
    Lease.start(access_token)
    host_url = get_wopi_url()
    office_url = get_office_url()
    if not host_url or not office_url:
        abort(HTTPStatus.SERVICE_UNAVAILABLE)
    wopi_src = '%s/%s/wopi/files/%s' % (
        host_url.rstrip('/'), quote(Transaction().database.name, safe=''), file_id)
    action_url = _editor_action_url(office_url, name, wopi_src)
    return _editor_form(action_url, access_token)


@app.route('/<database_name>/wopi/files/<file_id>', methods={'GET', 'POST'})
@with_pool
@with_transaction(readonly=False)
def file(request, pool, file_id):
    claim = _wopi_claim(request, pool, file_id)
    Model, binary, record = _claim_record(pool, claim)
    if request.method == 'GET':
        filename = _rename_field(Model, binary)
        name = getattr(record, filename) if filename else None
        name = _safe_name(name or claim['name'], claim['field'])
        extension = mimetypes.guess_extension(
            mimetypes.guess_type(name)[0] or '') or ''
        if extension and not name.lower().endswith(extension):
            name += extension
        return _json_response({
            'BaseFileName': name,
            'OwnerId': str(claim['user']),
            'Size': len(getattr(record, claim['field']) or b''),
            'UserId': str(claim['user']),
            'UserCanNotWriteRelative': True,
            'UserCanRename': bool(
                claim['writable'] and _rename_field(Model, binary)
                and _writable(pool, claim['model'], binary.filename,
                    record, Model._fields[binary.filename])),
            'UserCanWrite': bool(claim['writable']),
            'UserFriendlyName': str(claim['user']),
            'LastModifiedTime': _last_modified(record),
            'Version': _version(record),
            'ReadOnly': not claim['writable'],
            'SupportsExtendedLockLength': True,
            'SupportsGetLock': True,
            'SupportsLocks': True,
            'SupportsRename': bool(_rename_field(Model, binary)),
            'SupportsUpdate': bool(claim['writable']),
            })
    override = request.headers.get('X-WOPI-Override', '').upper()
    if override != 'GET_LOCK' and not claim['writable']:
        abort(403)
    Lock = pool.get('wopi.lock')
    lock = _current_lock(Lock, file_id)
    if override == 'GET_LOCK':
        return _response(X_WOPI_Lock=lock.value if lock else '')
    if override == 'LOCK':
        value = _lock_value(request)
        if lock and lock.value != value:
            return _lock_conflict(lock)
        expires = dt.datetime.utcnow() + dt.timedelta(seconds=LOCK_SECONDS)
        if lock:
            Lock.write([lock], {'expires_at': expires})
        else:
            Lock.create([{'file_id': file_id, 'value': value, 'expires_at': expires}])
        return _response()
    if override == 'REFRESH_LOCK':
        value = _lock_value(request)
        if not lock or lock.value != value:
            return _lock_conflict(lock)
        Lock.write([lock], {'expires_at': dt.datetime.utcnow()
            + dt.timedelta(seconds=LOCK_SECONDS)})
        return _response()
    if override == 'UNLOCK':
        value = _lock_value(request)
        if not lock or lock.value != value:
            return _lock_conflict(lock)
        Lock.delete([lock])
        return _response()
    if override == 'UNLOCK_AND_RELOCK':
        value = _lock_value(request)
        new_value = request.headers.get('X-WOPI-OldLock')
        if not lock or lock.value != new_value:
            return _lock_conflict(lock)
        Lock.write([lock], {'value': value, 'expires_at': dt.datetime.utcnow()
            + dt.timedelta(seconds=LOCK_SECONDS)})
        return _response()
    if override == 'DELETE':
        Model, _binary, record = _claim_record(pool, claim, write=True)
        requested = request.headers.get('X-WOPI-Lock', '')
        if lock and lock.value != requested:
            return _lock_conflict(lock)
        try:
            with Transaction().set_user(claim['user']), check_access():
                Model.write([record], {claim['field']: None})
        except AccessError:
            abort(403)
        if lock:
            Lock.delete([lock])
        return _response()
    if override == 'RENAME_FILE':
        Model, binary, record = _claim_record(pool, claim, write=True)
        filename = _rename_field(Model, binary)
        if not filename or not _writable(
                pool, claim['model'], filename, record,
                Model._fields[filename]):
            abort(501)
        requested = request.headers.get('X-WOPI-Lock', '')
        if lock and lock.value != requested:
            return _lock_conflict(lock)
        current_name = getattr(record, filename) or claim['name']
        result = _requested_name(request, current_name)
        if not result:
            return _response(status=400,
                X_WOPI_InvalidFileNameError='Invalid file name')
        new_name, stem = result
        try:
            with Transaction().set_user(claim['user']), check_access():
                Model.write([record], {filename: new_name})
        except AccessError:
            abort(403)
        record = Model(record.id)
        return _json_response({
            'Name': stem,
            # Collabora uses this optional value to keep using the same WOPI
            # resource after a rename.  The file ID deliberately does not
            # change when only the filename field is updated.
            'Url': request.url,
            'LastModifiedTime': _last_modified(record),
            }, X_WOPI_ItemVersion=_version(record))
    abort(501)


@app.route('/<database_name>/wopi/files/<file_id>/contents',
    methods={'GET', 'POST'})
@with_pool
@with_transaction(readonly=False)
def contents(request, pool, file_id):
    claim = _wopi_claim(request, pool, file_id)
    if request.method == 'GET':
        _Model, _binary, record = _claim_record(pool, claim)
        data = getattr(record, claim['field']) or b''
        content_type = (
            mimetypes.guess_type(claim['name'])[0]
            or 'application/octet-stream')
        return _response(
            data, Content_Type=content_type,
            X_WOPI_ItemVersion=_version(record))
    if request.headers.get('X-WOPI-Override', '').upper() != 'PUT':
        abort(501)
    Model, _binary, record = _claim_record(pool, claim, write=True)
    Lock = pool.get('wopi.lock')
    lock = _current_lock(Lock, file_id)
    requested = request.headers.get('X-WOPI-Lock', '')
    old_data = getattr(record, claim['field']) or b''
    if (lock and lock.value != requested) or (not lock and old_data):
        return _lock_conflict(lock)
    try:
        with Transaction().set_user(claim['user']), check_access():
            Model.write([record], {claim['field']: request.get_data()})
    except AccessError:
        abort(403)
    record = Model(record.id)
    return _json_response({
        'LastModifiedTime': _last_modified(record),
        }, X_WOPI_ItemVersion=_version(record))
