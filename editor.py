from functools import lru_cache
from pathlib import PurePath
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from trytond.config import config
from trytond.transaction import Transaction

class OfficeDiscoveryError(Exception):
    """Raised when the configured office server has no valid discovery."""


def get_office_url():
    """Return the URL of the single configured online office server."""
    return config.get('office', 'url', default=None)


def get_office_config_int(option, default=None):
    """Return an integer setting for the configured online office server."""
    return config.getint('office', option, default=default)


def get_wopi_config(option, default=None):
    return config.get('wopi', option, default=default)


def get_wopi_config_int(option, default=None):
    return config.getint('wopi', option, default=default)


def get_wopi_url():
    """Return the configured public URL of this WOPI host."""
    url = get_wopi_config('url')
    if url:
        return url
    return next((origin.strip() for origin in
            config.get('web', 'cors', default='').splitlines()
            if origin.strip()), None)


@lru_cache
def get_office_discovery(office_url, timeout):
    """Return the configured office server's WOPI discovery document."""
    discovery_url = office_url.rstrip('/') + '/hosting/discovery'
    try:
        request = Request(discovery_url, headers={'Accept': 'application/xml'})
        with urlopen(request, timeout=timeout) as response:
            return ElementTree.fromstring(response.read(1024 * 1024))
    except (HTTPError, URLError, OSError, ElementTree.ParseError) as exception:
        raise OfficeDiscoveryError from exception


def is_editable_filename(name):
    office_url = get_office_url()
    if not office_url:
        return False
    try:
        discovery = get_office_discovery(
            office_url, get_office_config_int('discovery_timeout', default=10))
    except OfficeDiscoveryError:
        return False
    extension = PurePath(name or '').suffix.lower().lstrip('.')
    return any(
        action.get('name') == 'edit'
        and action.get('ext', '').lower() == extension
        for action in discovery.iter('action'))


def get_editor_url(model, record, field, name=None):
    """Return the authenticated launch URL for a Tryton binary field.

    This is intentionally the URL of Tryton's launch endpoint, not the
    online-office URL and not a WOPI token.  It is therefore safe to expose on a
    record and can only be used by a browser with a valid Tryton session.
    """
    url_root = config.get('web', 'base_url', default=None) or get_wopi_url()
    if not url_root or not record:
        return None
    database = Transaction().database.name
    path = '/%s/wopi/open/%s/%s/%s' % (
        quote(database, safe=''), quote(model, safe=''), record,
        quote(field, safe=''))
    query = urlencode({'name': name}) if name else ''
    return '%s%s%s' % (url_root.rstrip('/'), path,
        ('?' + query) if query else '')
