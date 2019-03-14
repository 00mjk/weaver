from weaver.exceptions import ServiceNotFound, InvalidIdentifierValue
from weaver.warning import TimeZoneInfoAlreadySetWarning
from weaver.status import map_status
from datetime import datetime
from lxml import etree
from celery import Celery
from pyramid.httpexceptions import HTTPError as PyramidHTTPError
from pyramid.config import Configurator
from pyramid.registry import Registry
from pyramid.request import Request
from requests import HTTPError as RequestsHTTPError
from six.moves.urllib.parse import urlparse, parse_qs, urlunsplit, ParseResult
from distutils.dir_util import mkpath
from distutils.version import LooseVersion
from requests.structures import CaseInsensitiveDict
from webob.headers import ResponseHeaders, EnvironHeaders
from inspect import isclass
from typing import TYPE_CHECKING
import os
import six
import time
import pytz
import types
import re
import platform
import warnings
import logging
if TYPE_CHECKING:
    from weaver.typedefs import (
        AnyValue, AnyKey, AnySettingsContainer, AnyRegistryContainer, AnyHeadersContainer,
        HeadersType, SettingsType, JSON, XML, Number
    )
    from typing import Union, Any, Dict, List, AnyStr, Iterable, Optional

LOGGER = logging.getLogger(__name__)


# noinspection PyClassHasNoInit, PyPep8Coding, PyUnusuedLocal, PyMethodMayBeStatic
class _NullType:
    """Represents a ``null`` value to differentiate from ``None``."""
    def __eq__(self, other):
        return isinstance(other, _NullType) \
               or other is null \
               or (isclass(other) and issubclass(other, _NullType))

    def __nonzero__(self):
        return False
    __bool__ = __nonzero__
    __len__ = __nonzero__


null = _NullType()


def get_weaver_url(container):
    # type: (AnySettingsContainer) -> AnyStr
    """Retrieves the home URL of the `weaver` application."""
    return get_settings(container).get("weaver.url").rstrip('/').strip()


def get_any_id(info):
    # type: (JSON) -> Union[AnyStr, None]
    """Retrieves a dictionary `id-like` key using multiple common variations ``[id, identifier, _id]``.
    :param info: dictionary that potentially contains an `id-like` key.
    :returns: value of the matched `id-like` key or ``None`` if not found."""
    return info.get("id", info.get("identifier", info.get("_id")))


def get_any_value(info):
    # type: (JSON) -> AnyValue
    """Retrieves a dictionary `value-like` key using multiple common variations ``[href, value, reference]``.
    :param info: dictionary that potentially contains a `value-like` key.
    :returns: value of the matched `value-like` key or ``None`` if not found."""
    return info.get("href", info.get("value", info.get("reference", info.get("data"))))


def get_any_message(info):
    # type: (JSON) -> AnyStr
    """Retrieves a dictionary 'value'-like key using multiple common variations [message].
    :param info: dictionary that potentially contains a 'message'-like key.
    :returns: value of the matched 'message'-like key or an empty string if not found. """
    return info.get("message", "").strip()


def get_registry(container):
    # type: (AnyRegistryContainer) -> Registry
    """Retrieves the application ``registry`` from various containers referencing to it."""
    if isinstance(container, Celery):
        return container.conf["PYRAMID_REGISTRY"]
    if isinstance(container, (Configurator, Request)):
        return container.registry
    if isinstance(container, Registry):
        return container
    raise TypeError("Could not retrieve registry from container object of type [{}].".format(type(container)))


def get_settings(container):
    # type: (AnySettingsContainer) -> SettingsType
    """Retrieves the application ``settings`` from various containers referencing to it."""
    if isinstance(container, (Celery, Configurator, Request)):
        container = get_registry(container)
    if isinstance(container, Registry):
        return container.settings
    if isinstance(container, dict):
        return container
    raise TypeError("Could not retrieve settings from container object of type [{}]".format(type(container)))


def get_header(header_name, header_container):
    # type: (AnyStr, AnyHeadersContainer) -> Union[AnyStr, None]
    """
    Searches for the specified header by case/dash/underscore-insensitive ``header_name`` inside ``header_container``.
    """
    if header_container is None:
        return None
    headers = header_container
    if isinstance(headers, (ResponseHeaders, EnvironHeaders, CaseInsensitiveDict)):
        headers = dict(headers)
    if isinstance(headers, dict):
        headers = header_container.items()
    header_name = header_name.lower().replace('-', '_')
    for h, v in headers:
        if h.lower().replace('-', '_') == header_name:
            return v
    return None


def get_cookie_headers(header_container, cookie_header_name="Cookie"):
    # type: (AnyHeadersContainer, Optional[AnyStr]) -> HeadersType
    """
    Looks for ``cookie_header_name`` header within ``header_container``.
    :returns: new header container in the form ``{'Cookie': <found_cookie>}`` if it was matched, or empty otherwise.
    """
    try:
        cookie = get_header(cookie_header_name, header_container)
        if cookie:
            return dict(Cookie=get_header(cookie_header_name, header_container))
        return {}
    except KeyError:  # No cookie
        return {}


def get_url_without_query(url):
    # type: (Union[AnyStr, ParseResult]) -> AnyStr
    """Removes the query string part of an URL."""
    if isinstance(url, six.string_types):
        url = urlparse(url)
    if not isinstance(url, ParseResult):
        raise TypeError("Expected a parsed URL.")
    return urlunsplit(url[:4] + tuple(['']))


def is_valid_url(url):
    # type: (Union[AnyStr, None]) -> bool
    # noinspection PyBroadException
    try:
        parsed_url = urlparse(url)
        return True if all([parsed_url.scheme, ]) else False
    except Exception:
        return False


def parse_extra_options(option_str):
    """
    Parses the extra options parameter.

    The option_str is a string with coma separated ``opt=value`` pairs.
    Example::

        tempdir=/path/to/tempdir,archive_root=/path/to/archive

    :param option_str: A string parameter with the extra options.
    :return: A dict with the parsed extra options.
    """
    if option_str:
        try:
            extra_options = option_str.split(',')
            extra_options = dict([('=' in opt) and opt.split('=', 1) for opt in extra_options])
        except Exception:
            msg = "Can not parse extra-options: {}".format(option_str)
            from pyramid.exceptions import ConfigurationError
            raise ConfigurationError(msg)
    else:
        extra_options = {}
    return extra_options


def parse_service_name(url, protected_path):
    # type: (AnyStr, AnyStr) -> AnyStr
    parsed_url = urlparse(url)
    service_name = None
    if parsed_url.path.startswith(protected_path):
        parts_without_protected_path = parsed_url.path[len(protected_path)::].strip('/').split('/')
        if "proxy" in parts_without_protected_path:
            parts_without_protected_path.remove("proxy")
        if len(parts_without_protected_path) > 0:
            service_name = parts_without_protected_path[0]
    if not service_name:
        raise ServiceNotFound
    return service_name


def fully_qualified_name(obj):
    # type: (Any) -> AnyStr
    return '.'.join([obj.__module__, type(obj).__name__])


def now():
    # type: (...) -> datetime
    return localize_datetime(datetime.utcnow())


def now_secs():
    # type: (...) -> int
    """
    Return the current time in seconds since the Epoch.
    """
    return int(time.time())


def wait_secs(run_step=-1):
    secs_list = (2, 2, 2, 2, 2, 5, 5, 5, 5, 5, 10, 10, 10, 10, 10, 20, 20, 20, 20, 20, 30)
    if run_step >= len(secs_list):
        run_step = -1
    return secs_list[run_step]


def expires_at(hours=1):
    # type: (Optional[int]) -> int
    return now_secs() + hours * 3600


def localize_datetime(dt, tz_name="UTC"):
    # type: (datetime, Optional[AnyStr]) -> datetime
    """
    Provide a timezone-aware object for a given datetime and timezone name
    """
    tz_aware_dt = dt
    if dt.tzinfo is None:
        utc = pytz.timezone("UTC")
        aware = utc.localize(dt)
        timezone = pytz.timezone(tz_name)
        tz_aware_dt = aware.astimezone(timezone)
    else:
        warnings.warn("tzinfo already set", TimeZoneInfoAlreadySetWarning)
    return tz_aware_dt


def get_base_url(url):
    # type: (AnyStr) -> AnyStr
    """
    Obtains the base URL from the given ``url``.
    """
    parsed_url = urlparse(url)
    if not parsed_url.netloc or parsed_url.scheme not in ("http", "https"):
        raise ValueError("bad url")
    service_url = "%s://%s%s" % (parsed_url.scheme, parsed_url.netloc, parsed_url.path.strip())
    return service_url


def path_elements(path):
    # type: (AnyStr) -> List[AnyStr]
    elements = [el.strip() for el in path.split('/')]
    elements = [el for el in elements if len(el) > 0]
    return elements


def lxml_strip_ns(tree):
    # type: (XML) -> None
    for node in tree.iter():
        try:
            has_namespace = node.tag.startswith('{')
        except AttributeError:
            continue  # node.tag is not a string (node is a comment or similar)
        if has_namespace:
            node.tag = node.tag.split('}', 1)[1]


def ows_context_href(href, partial=False):
    # type: (AnyStr, Optional[bool]) -> JSON
    """Returns the complete or partial dictionary defining an ``OWSContext`` from a reference."""
    context = {"offering": {"content": {"href": href}}}
    if partial:
        return context
    return {"owsContext": context}


def pass_http_error(exception, expected_http_error):
    # type: (Exception, Union[PyramidHTTPError, Iterable[PyramidHTTPError]]) -> None
    """
    Given an `HTTPError` of any type (pyramid, requests), ignores (pass) the exception if the actual
    error matches the status code. Other exceptions are re-raised.

    :param exception: any `Exception` instance ("object" from a `try..except exception as "object"` block).
    :param expected_http_error: single or list of specific pyramid `HTTPError` to handle and ignore.
    :raise exception: if it doesn't match the status code or is not an `HTTPError` of any module.
    """
    if not hasattr(expected_http_error, "__iter__"):
        expected_http_error = [expected_http_error]
    if isinstance(exception, (PyramidHTTPError, RequestsHTTPError)):
        try:
            status_code = exception.status_code
        except AttributeError:
            # exception may be a response raised for status in which case status code is here:
            status_code = exception.response.status_code

        if status_code in [e.code for e in expected_http_error]:
            return
    raise exception


def raise_on_xml_exception(xml_node):
    """
    Raises an exception with the description if the XML response document defines an ExceptionReport.
    :param xml_node: instance of :class:`etree.Element`
    :raise Exception: on found ExceptionReport document.
    """
    # noinspection PyProtectedMember
    if not isinstance(xml_node, etree._Element):
        raise TypeError("Invalid input, expecting XML element node.")
    if "ExceptionReport" in xml_node.tag:
        node = xml_node
        while len(node.getchildren()):
            node = node.getchildren()[0]
        raise Exception(node.text)


def replace_caps_url(xml, url, prev_url=None):
    ns = {
        "ows": "http://www.opengis.net/ows/1.1",
        "xlink": "http://www.w3.org/1999/xlink"}
    doc = etree.fromstring(xml)
    # wms 1.1.1 onlineResource
    if "WMT_MS_Capabilities" in doc.tag:
        LOGGER.debug("replace proxy urls in wms 1.1.1")
        for element in doc.findall(".//OnlineResource[@xlink:href]", namespaces=ns):
            parsed_url = urlparse(element.get("{http://www.w3.org/1999/xlink}href"))
            new_url = url
            if parsed_url.query:
                new_url += "?" + parsed_url.query
            element.set("{http://www.w3.org/1999/xlink}href", new_url)
        xml = etree.tostring(doc)
    # wms 1.3.0 onlineResource
    elif "WMS_Capabilities" in doc.tag:
        LOGGER.debug("replace proxy urls in wms 1.3.0")
        for element in doc.findall(".//{http://www.opengis.net/wms}OnlineResource[@xlink:href]", namespaces=ns):
            parsed_url = urlparse(element.get("{http://www.w3.org/1999/xlink}href"))
            new_url = url
            if parsed_url.query:
                new_url += "?" + parsed_url.query
            element.set("{http://www.w3.org/1999/xlink}href", new_url)
        xml = etree.tostring(doc)
    # wps operations
    elif "Capabilities" in doc.tag:
        for element in doc.findall("ows:OperationsMetadata//*[@xlink:href]", namespaces=ns):
            element.set("{http://www.w3.org/1999/xlink}href", url)
        xml = etree.tostring(doc)
    elif prev_url:
        xml = xml.decode("utf-8", "ignore")
        xml = xml.replace(prev_url, url)
    return xml


def islambda(func):
    # type: (AnyStr) -> bool
    return isinstance(func, types.LambdaType) and func.__name__ == (lambda: None).__name__


first_cap_re = re.compile(r"(.)([A-Z][a-z]+)")
all_cap_re = re.compile(r"([a-z0-9])([A-Z])")


def convert_snake_case(name):
    # type: (AnyStr) -> AnyStr
    s1 = first_cap_re.sub(r"\1_\2", name)
    return all_cap_re.sub(r"\1_\2", s1).lower()


def parse_request_query(request):
    # type: (Request) -> Dict[AnyStr, Dict[AnyKey, AnyStr]]
    """
    :param request:
    :return: dict of dict where k=v are accessible by d[k][0] == v and q=k=v are accessible by d[q][k] == v, lowercase
    """
    queries = parse_qs(request.query_string.lower())
    queries_dict = dict()
    for q in queries:
        queries_dict[q] = dict()
        for i, kv in enumerate(queries[q]):
            kvs = kv.split('=')
            if len(kvs) > 1:
                queries_dict[q][kvs[0]] = kvs[1]
            else:
                queries_dict[q][i] = kvs[0]
    return queries_dict


def get_log_fmt():
    # type: (...) -> AnyStr
    return "[%(asctime)s] %(levelname)-8s [%(name)s] %(message)s"


def get_log_date_fmt():
    # type: (...) -> AnyStr
    return "%Y-%m-%d %H:%M:%S"


def get_log_monitor_msg(job_id, status, percent, message, location):
    # type: (AnyStr, AnyStr, Number, AnyStr, AnyStr) -> AnyStr
    return "Monitoring job {jobID} : [{status}] {percent} - {message} [{location}]".format(
        jobID=job_id, status=status, percent=percent, message=message, location=location
    )


def get_job_log_msg(status, message, progress=0, duration=None):
    # type: (AnyStr, AnyStr, Optional[Number], Optional[AnyStr]) -> AnyStr
    return "{d} {p:3d}% {s:10} {m}".format(d=duration or "", p=int(progress or 0), s=map_status(status), m=message)


def make_dirs(path, mode=0o755, exist_ok=True):
    """Alternative to ``os.makedirs`` with ``exists_ok`` parameter only available for ``python>3.5``."""
    if LooseVersion(platform.python_version()) >= LooseVersion('3.5'):
        os.makedirs(path, mode=mode, exist_ok=exist_ok)
        return
    dir_path = os.path.dirname(path)
    if not os.path.isfile(path) or not os.path.isdir(dir_path):
        for subdir in mkpath(dir_path):
            if not os.path.isdir(subdir):
                os.mkdir(subdir, mode)


REGEX_SEARCH_INVALID_CHARACTERS = re.compile(r"[^a-zA-Z0-9_\-]")
REGEX_ASSERT_INVALID_CHARACTERS = re.compile(r"^[a-zA-Z0-9_\-]+$")


def get_sane_name(name, min_len=3, max_len=None, assert_invalid=True, replace_character='_'):
    # type: (AnyStr, Optional[int], Optional[Union[int, None]], Optional[bool], Optional[AnyStr]) -> Union[AnyStr, None]
    """
    Returns a cleaned-up version of the input name, replacing invalid characters matched with
    ``REGEX_SEARCH_INVALID_CHARACTERS`` by ``replace_character``.

    :param name: value to clean
    :param min_len:
        Minimal length of ``name`` to be respected, raises or returns ``None`` on fail according to ``assert_invalid``.
    :param max_len:
        Maximum length of ``name`` to be respected, raises or returns trimmed ``name`` on fail according to
        ``assert_invalid``. If ``None``, condition is ignored for assertion or full ``name`` is returned respectively.
    :param assert_invalid: If ``True``, fail conditions or invalid characters will raise an error instead of replacing.
    :param replace_character: Single character to use for replacement of invalid ones if ``assert_invalid=False``.
    """
    if not isinstance(replace_character, six.string_types) and not len(replace_character) == 1:
        raise ValueError("Single replace character is expected, got invalid [{!s}]".format(replace_character))
    max_len = max_len or len(name)
    if assert_invalid:
        assert_sane_name(name, min_len, max_len)
    if name is None:
        return None
    name = name.strip()
    if len(name) < min_len:
        return None
    name = re.sub(REGEX_SEARCH_INVALID_CHARACTERS, replace_character, name[:max_len])
    return name


def assert_sane_name(name, min_len=3, max_len=None):
    """Asserts that the sane name respects conditions.

    .. seealso::
        - argument details in :function:`get_sane_name`
    """
    if name is None:
        raise InvalidIdentifierValue("Invalid name : {0}".format(name))
    name = name.strip()
    if '--' in name \
       or name.startswith('-') \
       or name.endswith('-') \
       or len(name) < min_len \
       or (max_len is not None and len(name) > max_len) \
       or not re.match(REGEX_ASSERT_INVALID_CHARACTERS, name):
        raise InvalidIdentifierValue("Invalid name : {0}".format(name))


def clean_json_text_body(body):
    # type: (AnyStr) -> AnyStr
    """
    Cleans a textual body field of superfluous characters to provide a better human-readable text in a JSON response.
    """
    # cleanup various escape characters and u'' stings
    replaces = [(',\n', ', '), (' \n', ' '), ('\"', '\''), ('\\', ''),
                ('u\'', '\''), ('u\"', '\''), ('\'\'', '\''), ('  ', ' ')]
    replaces_from = [r[0] for r in replaces]
    while any(rf in body for rf in replaces_from):
        for _from, _to in replaces:
            body = body.replace(_from, _to)

    body_parts = [p.strip() for p in body.split('\n') if p != '']               # remove new line and extra spaces
    body_parts = [p + '.' if not p.endswith('.') else p for p in body_parts]    # add terminating dot per sentence
    body_parts = [p[0].upper() + p[1:] for p in body_parts if len(p)]           # capitalize first word
    body_parts = ' '.join(p for p in body_parts if p)
    return body_parts