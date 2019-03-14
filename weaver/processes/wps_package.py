from weaver.config import get_weaver_configuration, WEAVER_CONFIGURATION_EMS
from weaver.processes import opensearch
from weaver.processes.constants import (
    WPS_INPUT, WPS_OUTPUT, WPS_COMPLEX, WPS_BOUNDINGBOX, WPS_LITERAL, WPS_REFERENCE,
    CWL_REQUIREMENT_APP_ESGF_CWT, CWL_REQUIREMENT_APP_WPS1, CWL_REQUIREMENT_APP_TYPES,
)
from weaver.processes.types import PROCESS_APPLICATION, PROCESS_WORKFLOW
from weaver.processes.sources import retrieve_data_source_url
from weaver.exceptions import (
    PackageTypeError, PackageRegistrationError, PackageExecutionError,
    PackageNotFound, PayloadNotFound
)
from weaver.formats import (
    CONTENT_TYPE_APP_JSON, CONTENT_TYPE_ANY_XML, CONTENT_TYPE_TEXT_PLAIN, get_cwl_file_format, clean_mime_type_format,
    get_extension,
)
from weaver.status import (
    STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_EXCEPTION, STATUS_FAILED, STATUS_COMPLIANT_PYWPS, STATUS_PYWPS_IDS,
    map_status,
)
from weaver.wps_restapi.swagger_definitions import process_uri
from weaver.wps import get_wps_output_dir
from weaver.utils import (
    get_job_log_msg, get_log_fmt, get_log_date_fmt, get_sane_name, get_settings, get_any_id, get_header,
    get_url_without_query, null
)
from owslib.wps import WebProcessingService, ComplexData
from pywps.inout.basic import BasicIO
from pywps.inout.literaltypes import AnyValue, AllowedValue, ALLOWEDVALUETYPE
from pywps.validator.mode import MODE
from pywps.app.Common import Metadata
from pywps import (
    Process,
    LiteralInput,
    LiteralOutput,
    ComplexInput,
    ComplexOutput,
    BoundingBoxInput,
    BoundingBoxOutput,
    Format,
)
from pyramid.httpexceptions import HTTPOk, HTTPServiceUnavailable
from pyramid_celery import celery_app as app
from collections import OrderedDict, Hashable
from six.moves.urllib.parse import urlparse
from typing import TYPE_CHECKING
from yaml.scanner import ScannerError
from cwltool.context import LoadingContext
from cwltool.context import RuntimeContext
import cwltool.factory
import cwltool
import lxml.etree
import yaml
import json
import tempfile
import shutil
import requests
import logging
import os
import six
if TYPE_CHECKING:
    from weaver.status import AnyStatusType
    from weaver.typedefs import (
        ToolPathObjectType, CWLFactoryCallable, CWL, AnyKey, AnyValue as AnyValueType, JSON, XML, Number
    )
    from typing import Any, AnyStr, Callable, Dict, List, Optional, Tuple, Type, Union
    from cwltool.process import Process as ProcessCWL
    from pywps.app import WPSRequest
    from pywps.response.execute import ExecuteResponse
    from owslib.wps import Input, Output

    # typing shortcuts
    WPS_Input_Type = Union[LiteralInput, ComplexInput, BoundingBoxInput]
    WPS_Output_Type = Union[LiteralOutput, ComplexOutput, BoundingBoxOutput]
    WPS_IO_Type = Union[WPS_Input_Type, WPS_Output_Type]
    OWS_Input_Type = Input
    OWS_Output_Type = Output
    OWS_IO_Type = Union[OWS_Input_Type, OWS_Output_Type]
    JSON_IO_Type = JSON
    CWL_Input_Type = CWL
    CWL_Output_Type = CWL
    CWL_IO_Type = Union[CWL_Input_Type, CWL_Output_Type]
    ANY_IO_Type = Union[CWL_IO_Type, JSON_IO_Type, WPS_IO_Type, OWS_IO_Type]


LOGGER = logging.getLogger(__name__)

__all__ = [
    "PACKAGE_EXTENSIONS",
    "WpsPackage",
    "get_process_definition",
    "get_process_location",
    "get_package_workflow_steps",
    "retrieve_package_job_log",
]

# package types and extensions
PACKAGE_EXTENSIONS = frozenset(["yaml", "yml", "json", "cwl", "job"])
PACKAGE_BASE_TYPES = frozenset(["string", "boolean", "float", "int", "integer", "long", "double"])
PACKAGE_LITERAL_TYPES = frozenset(list(PACKAGE_BASE_TYPES) + ["null", "Any"])
PACKAGE_COMPLEX_TYPES = frozenset(["File", "Directory"])
PACKAGE_ARRAY_BASE = "array"
PACKAGE_ARRAY_MAX_SIZE = six.MAXSIZE  # pywps doesn't allow None, so use max size
PACKAGE_ARRAY_ITEMS = frozenset(list(PACKAGE_BASE_TYPES) + list(PACKAGE_COMPLEX_TYPES))
PACKAGE_ARRAY_TYPES = frozenset(["{}[]".format(item) for item in PACKAGE_ARRAY_ITEMS])
PACKAGE_CUSTOM_TYPES = frozenset(["enum"])  # can be anything, but support "enum" which is more common
PACKAGE_DEFAULT_FILE_NAME = "package"
PACKAGE_LOG_FILE = "package_log_file"

# process execution progress
PACKAGE_PROGRESS_PREP_LOG = 1
PACKAGE_PROGRESS_LAUNCHING = 2
PACKAGE_PROGRESS_LOADING = 5
PACKAGE_PROGRESS_GET_INPUT = 6
PACKAGE_PROGRESS_CONVERT_INPUT = 8
PACKAGE_PROGRESS_RUN_CWL = 10
PACKAGE_PROGRESS_CWL_DONE = 95
PACKAGE_PROGRESS_PREP_OUT = 98
PACKAGE_PROGRESS_DONE = 100

# WPS object attribute -> all possible *other* naming variations
WPS_FIELD_MAPPING = {
    "identifier": ["Identifier", "ID", "id", "Id"],
    "title": ["Title"],
    "abstract": ["Abstract"],
    "metadata": ["Metadata"],
    "keywords": ["Keywords"],
    "allowed_values": ["AllowedValues", "allowedValues", "allowedvalues", "Allowed_Values", "Allowedvalues"],
    "allowed_collections": ["AllowedCollections", "allowedCollections", "allowedcollections", "Allowed_Collections",
                            "Allowedcollections"],
    "default": ["default_value", "defaultValue", "DefaultValue", "Default", "data_format"],
    "supported_values": ["SupportedValues", "supportedValues", "supportedvalues", "Supported_Values"],
    "supported_formats": ["SupportedFormats", "supportedFormats", "supportedformats", "Supported_Formats", "formats"],
    "additional_parameters": ["AdditionalParameters", "additionalParameters", "additionalparameters",
                              "Additional_Parameters"],
    "type": ["Type", "data_type", "dataType", "DataType", "Data_Type"],
    "min_occurs": ["minOccurs", "MinOccurs", "Min_Occurs", "minoccurs"],
    "max_occurs": ["maxOccurs", "MaxOccurs", "Max_Occurs", "maxoccurs"],
    "mime_type": ["mimeType", "MimeType", "mime-type", "Mime-Type", "MIME-Type"],
    "encoding": ["Encoding"],
}
# WPS fields that contain a structure corresponding to `Format` object
#   - keys must match `WPS_FIELD_MAPPING` keys
#   - fields are placed in order of relevance (prefer explicit format, then supported, and defaults as last resort)
WPS_FIELD_FORMAT = ["formats", "supported_formats", "supported_values", "default"]

# default format if missing (minimal requirement of one)
DefaultFormat = Format(mime_type=CONTENT_TYPE_TEXT_PLAIN)


def get_status_location_log_path(status_location, out_dir=None):
    # type: (AnyStr, Optional[AnyStr]) -> AnyStr
    log_path = os.path.splitext(status_location)[0] + ".log"
    return os.path.join(out_dir, os.path.split(log_path)[-1]) if out_dir else log_path


def retrieve_package_job_log(execution, job):
    try:
        # weaver package log every status update into this file (we no longer rely on the http monitoring)
        out_dir = get_wps_output_dir(get_settings(app))
        # if the process is a weaver package this status xml should be available in the process output dir
        log_path = get_status_location_log_path(execution.statusLocation, out_dir=out_dir)
        with open(log_path, 'r') as log_file:
            # Keep the first log entry which is the real start time and replace the following ones with the file content
            job.logs = job.logs[:1]
            for line in log_file:
                job.logs.append(line.rstrip('\n'))
        os.remove(log_path)
    except (KeyError, IOError):
        pass


def get_process_location(process_id_or_url, data_source=None):
    # type: (Union[Dict[AnyStr, Any], AnyStr], Optional[AnyStr]) -> AnyStr
    """
    Obtains the URL of a WPS REST DescribeProcess given the specified information.

    :param process_id_or_url: process "identifier" or literal URL to DescribeProcess WPS-REST location.
    :param data_source: identifier of the data source to map to specific ADES, or map to localhost if ``None``.
    :return: URL of EMS or ADES WPS-REST DescribeProcess.
    """
    # if an URL was specified, return it as is
    if urlparse(process_id_or_url).scheme != "":
        return process_id_or_url
    data_source_url = retrieve_data_source_url(data_source)
    process_id = get_sane_name(process_id_or_url)
    process_url = process_uri.format(process_id=process_id)
    return "{host}{path}".format(host=data_source_url, path=process_url)


def get_package_workflow_steps(package_dict_or_url):
    # type: (Union[Dict[AnyStr, Any], AnyStr]) -> List[Dict[AnyStr, AnyStr]]
    """
    :param package_dict_or_url: process package definition or literal URL to DescribeProcess WPS-REST location.
    :return: list of workflow steps as {"name": <name>, "reference": <reference>}
        where `name` is the generic package step name, and `reference` is the id/url of a registered WPS package.
    """
    if isinstance(package_dict_or_url, six.string_types):
        package_dict_or_url = _get_process_package(package_dict_or_url)
    workflow_steps_ids = list()
    package_type = _get_package_type(package_dict_or_url)
    if package_type == PROCESS_WORKFLOW:
        workflow_steps = package_dict_or_url.get("steps")
        for step in workflow_steps:
            step_package_ref = workflow_steps[step].get("run")
            # if a local file reference was specified, convert it to process id
            package_ref_name, package_ref_ext = os.path.splitext(step_package_ref)
            if urlparse(step_package_ref).scheme == "" and package_ref_ext.replace('.', '') in PACKAGE_EXTENSIONS:
                step_package_ref = package_ref_name
            workflow_steps_ids.append({"name": step, "reference": step_package_ref})
    return workflow_steps_ids


def _get_process_package(process_url):
    # type: (AnyStr) -> Tuple[CWL, AnyStr]
    """
    Retrieves the WPS process package content from given process ID or literal URL.

    :param process_url: process literal URL to DescribeProcess WPS-REST location.
    :return: tuple of package body as dictionary and package reference name.
    """

    def _package_not_found_error(ref):
        return PackageNotFound("Could not find workflow step reference: '{}'".format(ref))

    if not isinstance(process_url, six.string_types):
        raise _package_not_found_error(str(process_url))

    package_url = "{}/package".format(process_url)
    package_name = process_url.split('/')[-1]
    package_resp = requests.get(package_url, headers={"Accept": CONTENT_TYPE_APP_JSON}, verify=False)
    if package_resp.status_code != HTTPOk.code:
        raise _package_not_found_error(package_url)
    package_body = package_resp.json()

    if not isinstance(package_body, dict) or not len(package_body):
        raise _package_not_found_error(str(process_url))

    return package_body, package_name


def _get_process_payload(process_url):
    # type: (AnyStr) -> JSON
    """
    Retrieves the WPS process payload content from given process ID or literal URL.

    :param process_url: process literal URL to DescribeProcess WPS-REST location.
    :return: payload body as dictionary.
    """

    def _payload_not_found_error(ref):
        return PayloadNotFound("Could not find workflow step reference: '{}'".format(ref))

    if not isinstance(process_url, six.string_types):
        raise _payload_not_found_error(str(process_url))

    process_url = get_process_location(process_url)
    payload_url = "{}/payload".format(process_url)
    payload_resp = requests.get(payload_url, headers={"Accept": CONTENT_TYPE_APP_JSON}, verify=False)
    if payload_resp.status_code != HTTPOk.code:
        raise _payload_not_found_error(payload_url)
    payload_body = payload_resp.json()

    if not isinstance(payload_body, dict) or not len(payload_body):
        raise _payload_not_found_error(str(process_url))

    return payload_body


def _get_package_type(package_dict):
    # type: (CWL) -> Union[PROCESS_APPLICATION, PROCESS_WORKFLOW]
    return PROCESS_WORKFLOW if package_dict.get("class").lower() == "workflow" else PROCESS_APPLICATION


def _check_package_file(cwl_file_path_or_url):
    # type: (AnyStr) -> Tuple[AnyStr, bool]
    """
    Validates that the specified CWL file path or URL points to an existing and allowed file format.
    :param cwl_file_path_or_url: one of allowed file types path on disk, or an URL pointing to one served somewhere.
    :return: absolute_path, is_url: absolute path or URL, and boolean indicating if it is a remote URL file.
    :raises: PackageRegistrationError in case of missing file, invalid format or invalid HTTP status code.
    """
    is_url = False
    if urlparse(cwl_file_path_or_url).scheme != "":
        cwl_path = cwl_file_path_or_url
        cwl_resp = requests.head(cwl_path)
        is_url = True
        if cwl_resp.status_code != HTTPOk.code:
            raise PackageRegistrationError("Cannot find CWL file at: '{}'.".format(cwl_path))
    else:
        cwl_path = os.path.abspath(cwl_file_path_or_url)
        if not os.path.isfile(cwl_path):
            raise PackageRegistrationError("Cannot find CWL file at: '{}'.".format(cwl_path))

    file_ext = os.path.splitext(cwl_path)[1].replace('.', '')
    if file_ext not in PACKAGE_EXTENSIONS:
        raise PackageRegistrationError("Not a valid CWL file type: '{}'.".format(file_ext))
    return cwl_path, is_url


def _load_package_file(file_path):
    # type: (AnyStr) -> CWL
    """Loads the package in YAML/JSON format specified by the file path."""

    file_path, is_url = _check_package_file(file_path)
    # if URL, get the content and validate it by loading, otherwise load file directly
    # yaml properly loads json as well, error can print out the parsing error location
    try:
        if is_url:
            cwl_resp = requests.get(file_path, headers={"Accept": CONTENT_TYPE_TEXT_PLAIN})
            return yaml.safe_load(cwl_resp.content)
        with open(file_path, 'r') as f:
            return yaml.safe_load(f)
    except ScannerError as ex:
        raise PackageRegistrationError("Package parsing generated an error: [{!s}]".format(ex))


def _load_package_content(package_dict,                             # type: Dict
                          package_name=PACKAGE_DEFAULT_FILE_NAME,   # type: Optional[AnyStr]
                          data_source=None,                         # type: Optional[AnyStr]
                          only_dump_file=False,                     # type: Optional[bool]
                          tmp_dir=None,                             # type: Optional[AnyStr]
                          loading_context=None,                     # type: Optional[LoadingContext]
                          runtime_context=None,                     # type: Optional[RuntimeContext]
                          ):  # type: (...) -> Union[Tuple[CWLFactoryCallable, AnyStr, Dict], None]
    """
    Loads the package content to file in a temporary directory.
    Recursively processes sub-packages steps if the parent is a `Workflow` (CWL class).

    :param package_dict: package content representation as a json dictionary.
    :param package_name: name to use to create the package file.
    :param data_source: identifier of the data source to map to specific ADES, or map to localhost if ``None``.
    :param only_dump_file: specify if the ``CWLFactoryCallable`` should be validated and returned.
    :param tmp_dir: location of the temporary directory to dump files (warning: will be deleted on exit).
    :param loading_context: cwltool context used to create the cwl package
    :param runtime_context: cwltool context used to execute the cwl package
    :return:
        if ``only_dump_file`` is ``True``: ``None``
        otherwise, tuple of:
            - instance of ``CWLFactoryCallable``
            - package type (``PROCESS_WORKFLOW`` or ``PROCESS_APPLICATION``)
            - dict of each step with their package name that must be run
    """

    tmp_dir = tmp_dir or tempfile.mkdtemp()
    tmp_json_cwl = os.path.join(tmp_dir, package_name)

    # for workflows, retrieve each 'sub-package' file
    package_type = _get_package_type(package_dict)
    workflow_steps = get_package_workflow_steps(package_dict)
    step_packages = {}
    for step in workflow_steps:
        # generate sub-package file and update workflow step to point to it
        step_process_url = get_process_location(step["reference"], data_source)
        package_body, package_name = _get_process_package(step_process_url)
        _load_package_content(package_body, package_name, tmp_dir=tmp_dir,
                              data_source=data_source, only_dump_file=True)
        package_dict["steps"][step["name"]]["run"] = package_name
        step_packages[step["name"]] = package_name

    with open(tmp_json_cwl, 'w') as f:
        json.dump(package_dict, f)
    if only_dump_file:
        return

    cwl_factory = cwltool.factory.Factory(loading_context=loading_context, runtime_context=runtime_context)
    package = cwl_factory.make(tmp_json_cwl)    # type: CWLFactoryCallable
    shutil.rmtree(tmp_dir)
    return package, package_type, step_packages


def _is_cwl_array_type(io_info):
    # type: (CWL_IO_Type) -> Tuple[bool, AnyStr]
    """Verifies if the specified input/output corresponds to one of various CWL array type definitions.

    :return is_array: specifies if the input/output is of array type
    :return io_type: array element type if ``is_array`` is True, type of ``io_info`` otherwise.
    :raises PackageTypeError: if the array element is not supported.
    """
    is_array = False
    io_type = io_info["type"]

    # array type conversion when defined as dict of {"type": "array", "items": "<type>"}
    # validate against Hashable instead of 'dict' since 'OrderedDict'/'CommentedMap' can result in `isinstance()==False`
    if not isinstance(io_type, six.string_types) and not isinstance(io_type, Hashable) \
            and "items" in io_type and "type" in io_type:
        if not io_type["type"] == PACKAGE_ARRAY_BASE or io_type["items"] not in PACKAGE_ARRAY_ITEMS:
            raise PackageTypeError("Unsupported I/O 'array' definition: '{}'.".format(repr(io_info)))
        io_type = io_type["items"]
        is_array = True
    # array type conversion when defined as string '<type>[]'
    elif isinstance(io_type, six.string_types) and io_type in PACKAGE_ARRAY_TYPES:
        io_type = io_type[:-2]  # remove []
        if io_type not in PACKAGE_ARRAY_ITEMS:
            raise PackageTypeError("Unsupported I/O 'array' definition: '{}'.".format(repr(io_info)))
        is_array = True
    return is_array, io_type


def _is_cwl_enum_type(io_info):
    # type: (CWL_IO_Type) -> Tuple[bool, AnyStr, Union[List[AnyStr], None]]
    """Verifies if the specified input/output corresponds to a CWL enum definition.

    :return is_enum: specifies if the input/output is of enum type
    :return io_type: enum base type if ``is_enum`` is True, type of ``io_info`` otherwise.
    :return io_allow: permitted values of the enum
    :raises PackageTypeError: if the enum doesn't have required parameters to be valid.
    """
    io_type = io_info["type"]
    if not isinstance(io_type, dict) or "type" not in io_type or io_type["type"] not in PACKAGE_CUSTOM_TYPES:
        return False, io_type, None

    if "symbols" not in io_type:
        raise PackageTypeError("Unsupported I/O 'enum' definition: '{}'.".format(repr(io_info)))
    io_allow = io_type["symbols"]
    if not isinstance(io_allow, list) or len(io_allow) < 1:
        raise PackageTypeError("Invalid I/O 'enum.symbols' definition: '{}'.".format(repr(io_info)))

    # validate matching types in allowed symbols and convert to supported CWL type
    first_allow = io_allow[0]
    for e in io_allow:
        if type(e) is not type(first_allow):
            raise PackageTypeError("Ambiguous types in I/O 'enum.symbols' definition: '{}'.".format(repr(io_info)))
    if isinstance(first_allow, six.string_types):
        io_type = "string"
    elif isinstance(first_allow, float):
        io_type = "float"
    elif isinstance(first_allow, int):
        io_type = "int"
    else:
        raise PackageTypeError("Unsupported I/O 'enum' base type: `{0}`, from definition: `{1}`."
                               .format(str(type(first_allow)), repr(io_info)))

    return True, io_type, io_allow


# noinspection PyUnusedLocal
def _cwl2wps_io(io_info, io_select):
    # type:(CWL_IO_Type, AnyStr) -> WPS_IO_Type
    """Converts input/output parameters from CWL types to WPS types.
    :param io_info: parsed IO of a CWL file
    :param io_select: ``WPS_INPUT`` or ``WPS_OUTPUT`` to specify desired WPS type conversion.
    :returns: corresponding IO in WPS format
    """
    is_input = False
    is_output = False
    # TODO: BoundingBox not implemented
    if io_select == WPS_INPUT:
        is_input = True
        io_literal = LiteralInput       # type: Union[Type[LiteralInput], Type[LiteralOutput]]
        io_complex = ComplexInput       # type: Union[Type[ComplexInput], Type[ComplexOutput]]
        # io_bbox = BoundingBoxInput      # type: Union[Type[BoundingBoxInput], Type[BoundingBoxOutput]]
    elif io_select == WPS_OUTPUT:
        is_output = True
        io_literal = LiteralOutput      # type: Union[Type[LiteralInput], Type[LiteralOutput]]
        io_complex = ComplexOutput      # type: Union[Type[ComplexInput], Type[ComplexOutput]]
        # io_bbox = BoundingBoxOutput     # type: Union[Type[BoundingBoxInput], Type[BoundingBoxOutput]]
    else:
        raise PackageTypeError("Unsupported I/O info definition: `{0}` with `{1}`.".format(repr(io_info), io_select))

    io_name = io_info["name"]
    io_type = io_info["type"]
    io_min_occurs = 1
    io_max_occurs = 1
    io_allow = AnyValue
    io_mode = MODE.NONE

    # obtain real type if "default" or shorthand "<type>?" was in CWL, which defines "type" as `["null", <type>]`
    if isinstance(io_type, list) and "null" in io_type:
        if not len(io_type) == 2:
            raise PackageTypeError("Unsupported I/O type parsing for info: `{0}` with `{1}`."
                                   .format(repr(io_info), io_select))
        LOGGER.debug("I/O parsed for 'default'")
        io_type = io_type[1] if io_type[0] == "null" else io_type[0]
        io_info["type"] = io_type

    # convert array types
    is_array, array_elem = _is_cwl_array_type(io_info)
    if is_array:
        LOGGER.debug("I/O parsed for 'array'")
        io_type = array_elem
        io_max_occurs = PACKAGE_ARRAY_MAX_SIZE

    # convert enum types
    is_enum, enum_type, enum_allow = _is_cwl_enum_type(io_info)
    if is_enum:
        LOGGER.debug("I/O parsed for 'enum'")
        io_type = enum_type
        io_allow = enum_allow
        io_mode = MODE.SIMPLE  # allowed value validator must be set for input

    # debug info for unhandled types conversion
    if not isinstance(io_type, six.string_types):
        LOGGER.debug("is_array:      '{}'".format(repr(is_array)))
        LOGGER.debug("array_elem:    '{}'".format(repr(array_elem)))
        LOGGER.debug("is_enum:       '{}'".format(repr(is_enum)))
        LOGGER.debug("enum_type:     '{}'".format(repr(enum_type)))
        LOGGER.debug("enum_allow:    '{}'".format(repr(enum_allow)))
        LOGGER.debug("io_info:       '{}'".format(repr(io_info)))
        LOGGER.debug("io_type:       '{}'".format(repr(io_type)))
        LOGGER.debug("type(io_type): '{}'".format(type(io_type)))
        raise TypeError("I/O type has not been properly decoded. Should be a string, got:`{!r}`".format(io_type))

    # literal types
    if is_enum or io_type in PACKAGE_LITERAL_TYPES:
        if io_type == "Any":
            io_type = "anyvalue"
        if io_type == "null":
            io_type = "novalue"
        if io_type in ["int", "integer", "long"]:
            io_type = "integer"
        if io_type in ["float", "double"]:
            io_type = "float"
        # keywords commonly used by I/O
        kw = {
            "identifier": io_name,
            "title": io_info.get("label", ""),
            "abstract": io_info.get("doc", ""),
            "data_type": io_type,
            "mode": io_mode,
        }
        if is_input:
            kw["default"] = io_info.get("default", None)
            kw["allowed_values"] = io_allow
            kw["min_occurs"] = io_min_occurs
            kw["max_occurs"] = io_max_occurs
        return io_literal(**kw)
    # complex types
    else:
        # keywords commonly used by I/O
        kw = {
            "identifier": io_name,
            "title": io_info.get("label", io_name),
            "abstract": io_info.get("doc", ""),
        }
        if "format" in io_info:
            kw["supported_formats"] = [Format(clean_mime_type_format(io_info["format"]))]
            kw["mode"] = MODE.SIMPLE
        else:
            # we need to minimally add 1 format, otherwise empty list is evaluated as None by pywps
            # when "supported_formats" is None, the process's json property raises because of it cannot iterate formats
            kw["supported_formats"] = [DefaultFormat]
            kw["mode"] = MODE.NONE
        if is_output:
            if io_type == "Directory":
                kw["as_reference"] = True
            if io_type == "File":
                has_contents = io_info.get("contents") is not None
                kw["as_reference"] = False if has_contents else True
        else:
            kw.update({
                "min_occurs": io_min_occurs,
                "max_occurs": io_max_occurs,
            })
        return io_complex(**kw)


def _any2wps_literal_datatype(io_type, is_value):
    # type: (AnyValueType, bool) -> Union[AnyStr, Type[null]]
    """
    Solves common data-type names to supported ones.
    Verification is accomplished by name when ``is_value=False``, otherwise with python ``type`` when ``is_value=True``.
    """
    if isinstance(io_type, six.string_types):
        if not is_value:
            if io_type in ["date", "time", "dateTime", "anyURI"]:
                return "string"
            if io_type in ["scale", "angle", "float", "double"]:
                return "float"
            if io_type in ["int", "integer", "positiveInteger", "nonNegativeInteger"]:
                return "integer"
            if io_type in ["bool", "boolean"]:
                return "boolean"
        return "string"
    if is_value and isinstance(io_type, bool):
        return "boolean"
    if is_value and isinstance(io_type, int):
        return "integer"
    if is_value and isinstance(io_type, float):
        return "float"
    return null


def _json2wps_datatype(io_info):
    # type: (JSON_IO_Type) -> AnyStr
    """
    Guesses the literal data-type from I/O JSON information in order to allow creation of the corresponding I/O WPS.
    Defaults to ``string`` if no suitable guess can be accomplished.
    """
    io_type = _get_field(io_info, "type", search_variations=False, pop_found=True)
    if str(io_type).lower() == WPS_LITERAL:
        io_type = null
    io_guesses = [
        (io_type, False),
        (_get_field(io_info, "type", search_variations=True), False),
        (_get_field(io_info, "default", search_variations=True), True),
        (_get_field(io_info, "allowed_values", search_variations=True), True),
        (_get_field(io_info, "supported_values", search_variations=True), True)
    ]
    for io_guess, is_value in io_guesses:
        if io_type:
            break
        if isinstance(io_guess, list) and len(io_guess):
            io_guess = io_guess[0]
        io_type = _any2wps_literal_datatype(io_guess, is_value)
    if not isinstance(io_type, six.string_types):
        LOGGER.warning("Failed literal data-type guess, using default 'string' for I/O '{}'."
                       .format(_get_field(io_info, "identifier", search_variations=True)))
        return "string"
    return io_type


def _json2wps_field(field_info, field_category):
    # type: (JSON_IO_Type, AnyStr) -> Any
    """
    Converts an I/O field from a JSON literal data, list, or dictionary to corresponding WPS types.
    :param field_info: literal data or information container describing the type to be generated.
    :param field_category: one of ``WPS_FIELD_MAPPING`` keys to indicate how to parse ``field_info``.
    """
    if field_category == "allowed_values":
        if isinstance(field_info, AllowedValue):
            return field_info
        if isinstance(field_info, dict):
            field_info.pop("type", None)
            return AllowedValue(**field_info)
        if isinstance(field_info, six.string_types):
            return AllowedValue(value=field_info, allowed_type=ALLOWEDVALUETYPE.VALUE)
        if isinstance(field_info, list):
            return AllowedValue(minval=min(field_info), maxval=max(field_info), allowed_type=ALLOWEDVALUETYPE.RANGE)
    elif field_category == "supported_formats":
        if isinstance(field_info, dict):
            return Format(**field_info)
        if isinstance(field_info, six.string_types):
            return Format(field_info)
    elif field_category == "metadata":
        if isinstance(field_info, dict):
            return Metadata(**field_info)
        if isinstance(field_info, six.string_types):
            return Metadata(field_info)
    elif field_category == "keywords" and isinstance(field_info, list):
        return field_info
    elif field_category in ["identifier", "title", "abstract"] and isinstance(field_info, six.string_types):
        return field_info
    return None


def _json2wps_io(io_info, io_select):
    # type: (JSON_IO_Type, Union[WPS_INPUT, WPS_OUTPUT]) -> WPS_IO_Type
    """Converts an I/O from a JSON dict to WPS types.
    :param io_info: I/O in JSON dict format.
    :param io_select: ``WPS_INPUT`` or ``WPS_OUTPUT`` to specify desired WPS type conversion.
    :return: corresponding I/O in WPS format.
    """

    io_info["identifier"] = _get_field(io_info, "identifier", search_variations=True, pop_found=True)

    rename = {
        "formats": "supported_formats",
        "minOccurs": "min_occurs",
        "maxOccurs": "max_occurs",
    }
    remove = [
        "id",
        "workdir",
        "any_value",
        "data_format",
        "data",
        "file",
        "mimetype",
        "encoding",
        "schema",
        "asreference",
        "additionalParameters",
    ]
    replace_values = {"unbounded": PACKAGE_ARRAY_MAX_SIZE}

    transform_json(io_info, rename=rename, remove=remove, replace_values=replace_values)

    # convert allowed value objects
    values = _get_field(io_info, "allowed_values", search_variations=True, pop_found=True)
    if values is not null:
        if isinstance(values, list) and len(values) > 0:
            io_info["allowed_values"] = list()
            for allow_value in values:
                io_info["allowed_values"].append(_json2wps_field(allow_value, "allowed_values"))
        else:
            io_info["allowed_values"] = AnyValue

    # convert supported format objects
    formats = _get_field(io_info, "supported_formats", search_variations=True, pop_found=True)
    if formats is not null:
        for fmt in formats:
            fmt["mime_type"] = _get_field(fmt, "mime_type", search_variations=True, pop_found=True)
            fmt.pop("maximumMegabytes", None)
            fmt.pop("default", None)
        io_info["supported_formats"] = [_json2wps_field(fmt, "supported_formats") for fmt in formats]

    # convert metadata objects
    metadata = _get_field(io_info, "metadata", search_variations=True, pop_found=True)
    if metadata is not null:
        io_info["metadata"] = [_json2wps_field(meta, "metadata") for meta in metadata]

    # convert literal fields specified as is
    for field in ["identifier", "title", "abstract", "keywords"]:
        value = _get_field(io_info, field, search_variations=True, pop_found=True)
        if value is not null:
            io_info[field] = _json2wps_field(value, field)

    # convert by type, add missing required arguments and
    # remove additional arguments according to each case
    io_type = io_info.pop("type", WPS_COMPLEX)  # only ComplexData doesn't have "type"
    if io_select == WPS_INPUT:
        if io_type in (WPS_REFERENCE, WPS_COMPLEX):
            io_info.pop("data_type", None)
            if "supported_formats" not in io_info:
                io_info["supported_formats"] = [DefaultFormat]
            if ("max_occurs", "unbounded") in io_info.items():
                io_info["max_occurs"] = PACKAGE_ARRAY_MAX_SIZE
            io_info.pop("supported_values", None)
            return ComplexInput(**io_info)
        if io_type == WPS_BOUNDINGBOX:
            io_info.pop("supported_formats", None)
            io_info.pop("supportedCRS", None)
            return BoundingBoxInput(**io_info)
        if io_type == WPS_LITERAL:
            io_info.pop("supported_formats", None)
            io_info.pop("literalDataDomains", None)
            io_info["data_type"] = _json2wps_datatype(io_info)
            return LiteralInput(**io_info)
    elif io_select == WPS_OUTPUT:
        io_info.pop("min_occurs", None)
        io_info.pop("max_occurs", None)
        io_info.pop("allowed_values", None)
        io_info.pop("default", None)
        if io_type in (WPS_REFERENCE, WPS_COMPLEX):
            io_info.pop("supported_values", None)
            return ComplexOutput(**io_info)
        if io_type == WPS_BOUNDINGBOX:
            io_info.pop("supported_formats", None)
            return BoundingBoxOutput(**io_info)
        if io_type == WPS_LITERAL:
            io_info.pop("supported_formats", None)
            io_info["data_type"] = _json2wps_datatype(io_info)
            return LiteralOutput(**io_info)
    raise PackageTypeError("Unknown conversion from dict to WPS type (type={0}, mode={1}).".format(io_type, io_select))


def _wps2json_io(io_wps):
    # type: (WPS_IO_Type) -> JSON_IO_Type
    """Converts a PyWPS I/O into a dictionary based version with keys corresponding to standard names (WPS 2.0)."""

    if not isinstance(io_wps, BasicIO):
        raise PackageTypeError("Invalid type, expected `BasicIO`, got: `[{0!r}] {1!r}`".format(type(io_wps), io_wps))
    # in some cases (Complex I/O), 'as_reference=True' causes "type" to be overwritten, revert it back
    # noinspection PyUnresolvedReferences
    io_wps_json = io_wps.json

    rename = {
        u"identifier": u"id",
        u"supported_formats": u"formats",
        u"mime_type": u"mimeType",
        u"min_occurs": u"minOccurs",
        u"max_occurs": u"maxOccurs",
    }
    replace_values = {
        PACKAGE_ARRAY_MAX_SIZE: "unbounded",
    }
    replace_func = {
        "maxOccurs": str,
        "minOccurs": str,
    }

    transform_json(io_wps_json, rename=rename, replace_values=replace_values, replace_func=replace_func)

    if "type" in io_wps_json and io_wps_json["type"] == "reference":
        io_wps_json["type"] = WPS_COMPLEX

    # minimum requirement of 1 format object which defines mime-type
    if io_wps_json["type"] == WPS_COMPLEX:
        if "formats" not in io_wps_json or not len(io_wps_json["formats"]):
            io_wps_json["formats"] = [DefaultFormat.json]
        for io_format in io_wps_json["formats"]:
            transform_json(io_format, rename=rename, replace_values=replace_values, replace_func=replace_func)

        # set 'default' format if it matches perfectly, or if only mime-type matches and it is the only available one
        # (this avoid 'encoding' possibly not matching due to CWL not providing this information)
        io_default = _get_field(io_wps_json, "default", search_variations=True)
        for io_format in io_wps_json["formats"]:
            io_format["default"] = (io_default != null and _matching_formats(io_format, io_default))
        if io_default and len(io_wps_json["formats"]) == 1 and not io_wps_json["formats"][0]["default"]:
            io_default_mime_type = _get_field(io_default, "mime_type", search_variations=True)
            io_single_fmt_mime_type = _get_field(io_wps_json["formats"][0], "mime_type", search_variations=True)
            io_wps_json["formats"][0]["default"] = (io_default_mime_type == io_single_fmt_mime_type)

    return io_wps_json


def _get_field(io_object, field, search_variations=False, pop_found=False):
    # type: (ANY_IO_Type, str, bool, bool) -> Any
    """
    Gets a field by name from various I/O object types.

    :returns: matched value (including search variations if enabled), or ``null``.
    """
    if isinstance(io_object, dict):
        value = io_object.get(field, null)
        if value is not null:
            if pop_found:
                io_object.pop(field)
            return value
    else:
        value = getattr(io_object, field, null)
        if value is not null:
            return value
    if search_variations and field in WPS_FIELD_MAPPING:
        for var in WPS_FIELD_MAPPING[field]:
            value = _get_field(io_object, var, pop_found=pop_found)
            if value is not null:
                return value
    return null


def _set_field(io_object, field, value, force=False):
    # type: (Union[BasicIO, Dict[str, Any]], str, Any, Optional[bool]) -> None
    """
    Sets a field by name into various I/O object types.
    Field value is set only if not ``null`` to avoid inserting data considered `invalid`.
    If ``force=True``, verification of ``null`` value is ignored.
    """
    if value is not null or force:
        if isinstance(io_object, dict):
            io_object[field] = value
            return
        setattr(io_object, field, value)


def _matching_formats(format1, format2):
    # type: (Union[Format, JSON], Union[Format, JSON]) -> bool
    """Verifies for matching formats."""
    mime_type1 = _get_field(format1, "mime_type", search_variations=True)
    mime_type2 = _get_field(format2, "mime_type", search_variations=True)
    encoding1 = _get_field(format1, "encoding", search_variations=True)
    encoding2 = _get_field(format2, "encoding", search_variations=True)
    if mime_type1 == mime_type2 and encoding1 == encoding2 and \
            all(f != null for f in [mime_type1, mime_type2, encoding1, encoding2]):
        return True
    return False


def _are_different_and_set(value1, value2):
    # type: (Any, Any) -> bool
    """
    Compares two values and returns ``True`` only if both are not ``null``, are of same ``type`` and of different value.
    """
    if (value1 == null and value2 == null) or value1 == value2:
        return False
    type1 = str if isinstance(value1, six.string_types) else type(value1)
    type2 = str if isinstance(value2, six.string_types) else type(value2)
    if type1 != type2:
        return False
    return True


def _merge_package_io(wps_io_list, cwl_io_list, io_select):
    # type: (List[ANY_IO_Type], List[CWL_IO_Type], Union[WPS_INPUT, WPS_OUTPUT]) -> List[JSON_IO_Type]
    """
    Update I/O definitions to use for process creation and returned by GetCapabilities, DescribeProcess.
    If WPS I/O definitions where provided during deployment, update them instead of `CWL-to-WPS` converted I/O.
    Otherwise, provide minimum field requirements that can be retrieved from CWL definitions.

    Removes any deployment WPS I/O definitions that don't match any CWL I/O by ID.
    Adds missing deployment WPS I/O definitions using expected CWL I/O IDs.

    :param wps_io_list: list of WPS I/O (as json) passed during process deployment.
    :param cwl_io_list: list of CWL I/O converted to WPS-like I/O for counter-validation.
    :param io_select: ``WPS_INPUT`` or ``WPS_OUTPUT`` to specify desired WPS type conversion.
    :returns: list of validated/updated WPS I/O for the process.
    """
    if not isinstance(cwl_io_list, list):
        raise PackageTypeError("CWL I/O definitions must be provided, empty list if none required.")
    if not wps_io_list:
        wps_io_list = list()
    wps_io_dict = OrderedDict((_get_field(wps_io, "identifier", search_variations=True), wps_io)
                              for wps_io in wps_io_list)
    cwl_io_dict = OrderedDict((_get_field(cwl_io, "identifier", search_variations=True), cwl_io)
                              for cwl_io in cwl_io_list)
    missing_io_list = set(cwl_io_dict) - set(wps_io_dict)
    updated_io_list = list()
    # missing WPS I/O are inferred only using CWL->WPS definitions
    for cwl_id in missing_io_list:
        updated_io_list.append(cwl_io_dict[cwl_id])
    # evaluate provided WPS I/O definitions
    for wps_io_json in wps_io_list:
        wps_id = _get_field(wps_io_json, "identifier", search_variations=True)
        # WPS I/O by id not matching any CWL->WPS I/O are discarded, otherwise merge details
        if wps_id not in cwl_io_dict:
            continue
        cwl_io = cwl_io_dict[wps_id]
        cwl_io_json = cwl_io.json
        updated_io_list.append(cwl_io)
        # enforce expected CWL->WPS I/O type and append required parameters if missing
        cwl_identifier = _get_field(cwl_io_json, "identifier", search_variations=True)
        cwl_title = _get_field(wps_io_json, "title", search_variations=True)
        wps_io_json.update({"type": _get_field(cwl_io_json, "type"),
                            "identifier": cwl_identifier,
                            "title": cwl_title if cwl_title is not null else cwl_identifier})
        wps_io = _json2wps_io(wps_io_json, io_select)
        # retrieve any complementing fields (metadata, keywords, etc.) passed as WPS input
        for field_type in WPS_FIELD_MAPPING:
            cwl_field = _get_field(cwl_io, field_type)
            wps_field = _get_field(wps_io, field_type)
            # override if CWL->WPS was missing but is provided by WPS, or if both are provided but different (keep WPS)
            if _are_different_and_set(wps_field, cwl_field) or (wps_field != null and cwl_field == null):
                _set_field(updated_io_list[-1], field_type, wps_field)
    return updated_io_list


def transform_json(json_data,               # type: ANY_IO_Type
                   rename=None,             # type: Optional[Dict[AnyKey, Any]]
                   remove=None,             # type: Optional[List[AnyKey]]
                   add=None,                # type: Optional[Dict[AnyKey, Any]]
                   replace_values=None,     # type: Optional[Dict[AnyKey, Any]]
                   replace_func=None,       # type: Optional[Dict[AnyKey, Callable[[Any], Any]]]
                   ):                       # type: (...) -> ANY_IO_Type
    """
    Transforms the input json_data with different methods.
    The transformations are applied in the same order as the arguments.
    """
    rename = rename or {}
    remove = remove or []
    add = add or {}
    replace_values = replace_values or {}
    replace_func = replace_func or {}

    # rename
    for k, v in rename.items():
        if k in json_data:
            json_data[v] = json_data.pop(k)

    # remove
    for r in remove:
        json_data.pop(r, None)

    # add
    for k, v in add.items():
        json_data[k] = v

    # replace values
    for key, value in json_data.items():
        for old_value, new_value in replace_values.items():
            if value == old_value:
                json_data[key] = new_value

    # replace with function call
    for k, func in replace_func.items():
        if k in json_data:
            json_data[k] = func(json_data[k])

    # also rename if the type of the value is a list of dicts
    for key, value in json_data.items():
        if isinstance(value, list):
            for nested_item in value:
                if isinstance(nested_item, dict):
                    for k, v in rename.items():
                        if k in nested_item:
                            nested_item[v] = nested_item.pop(k)
                    for k, func in replace_func.items():
                        if k in nested_item:
                            nested_item[k] = func(nested_item[k])
    return json_data


def _merge_package_inputs_outputs(wps_inputs_list,      # type: List[ANY_IO_Type]
                                  cwl_inputs_list,      # type: List[CWL_Input_Type]
                                  wps_outputs_list,     # type: List[ANY_IO_Type]
                                  cwl_outputs_list,     # type: List[CWL_Output_Type]
                                  ):                    # type: (...) -> Tuple[List[JSON_IO_Type], List[JSON_IO_Type]]
    """
    Merges I/O definitions to use for process creation and returned by ``GetCapabilities``, ``DescribeProcess``
    using the `WPS` specifications (from request ``POST``) and `CWL` specifications (extracted from file).
    """
    wps_inputs_merged = _merge_package_io(wps_inputs_list, cwl_inputs_list, WPS_INPUT)
    wps_outputs_merged = _merge_package_io(wps_outputs_list, cwl_outputs_list, WPS_OUTPUT)
    return [_wps2json_io(i) for i in wps_inputs_merged], [_wps2json_io(o) for o in wps_outputs_merged]


def _get_package_io(package_factory, io_select, as_json):
    # type: (CWLFactoryCallable, AnyStr, bool) -> List[Union[JSON_IO_Type, WPS_IO_Type]]
    """
    Retrieves I/O definitions from a validated ``CWLFactoryCallable``. Returned I/O format depends on value ``as_json``.
    """
    if io_select == WPS_OUTPUT:
        io_attrib = "outputs_record_schema"
    elif io_select == WPS_INPUT:
        io_attrib = "inputs_record_schema"
    else:
        raise PackageTypeError("Unknown I/O selection: '{}'.".format(io_select))
    cwl_package_io = getattr(package_factory.t, io_attrib)
    wps_package_io = [_cwl2wps_io(io, io_select) for io in cwl_package_io["fields"]]
    if as_json:
        return [_wps2json_io(io) for io in wps_package_io]
    return wps_package_io


def _get_package_inputs(package_factory, as_json=False):
    # type: (CWLFactoryCallable, Optional[bool]) -> List[Union[JSON_IO_Type, WPS_IO_Type]]
    """Generates `WPS-like` ``inputs`` using parsed CWL package input definitions."""
    return _get_package_io(package_factory, io_select=WPS_INPUT, as_json=as_json)


def _get_package_outputs(package_factory, as_json=False):
    # type: (CWLFactoryCallable, Optional[bool]) -> List[Union[JSON_IO_Type, WPS_IO_Type]]
    """Generates `WPS-like` ``outputs`` using parsed CWL package output definitions."""
    return _get_package_io(package_factory, io_select=WPS_OUTPUT, as_json=as_json)


def _get_package_inputs_outputs(package_factory,    # type: CWLFactoryCallable
                                as_json=False,      # type: Optional[bool]
                                ):
    # type: (...) -> Tuple[Union[JSON_IO_Type, WPS_IO_Type], Union[JSON_IO_Type, WPS_IO_Type]]
    """Generates `WPS-like` ``(inputs, outputs)`` tuple using parsed CWL package definitions."""
    return (_get_package_io(package_factory, io_select=WPS_INPUT, as_json=as_json),
            _get_package_io(package_factory, io_select=WPS_OUTPUT, as_json=as_json))


def _update_package_metadata(wps_package_metadata, cwl_package_package):
    # type: (JSON, CWL) -> None
    """Updates the package `WPS` metadata dictionary from extractable `CWL` package definition."""
    wps_package_metadata["title"] = wps_package_metadata.get("title", cwl_package_package.get("label", ""))
    wps_package_metadata["abstract"] = wps_package_metadata.get("abstract", cwl_package_package.get("doc", ""))

    if "$schemas" in cwl_package_package and isinstance(cwl_package_package["$schemas"], list) \
            and "$namespaces" in cwl_package_package and isinstance(cwl_package_package["$namespaces"], dict):
        metadata = wps_package_metadata.get("metadata", list())
        namespaces_inv = {v: k for k, v in cwl_package_package["$namespaces"]}
        for schema in cwl_package_package["$schemas"]:
            for namespace_url in namespaces_inv:
                if schema.startswith(namespace_url):
                    metadata.append({"title": namespaces_inv[namespace_url], "href": schema})
        wps_package_metadata["metadata"] = metadata

    if "s:keywords" in cwl_package_package and isinstance(cwl_package_package["s:keywords"], list):
        wps_package_metadata["keywords"] = list(set(wps_package_metadata.get("keywords", list)) |
                                                set(cwl_package_package.get("s:keywords")))


def _ows2json_io(ows_io):
    # type: (OWS_IO_Type) -> JSON_IO_Type
    """Converts I/O from :module:`owslib.wps` to JSON."""
    def _complex2format(data):
        # type: (ComplexData) -> JSON
        return {
            "mimeType": data.mimeType,
            "encoding": data.encoding,
            "schema": data.schema,
        }

    json_io = dict()
    for field in WPS_FIELD_MAPPING:
        value = _get_field(ows_io, field, search_variations=True)
        # preserve numeric values (ex: "minOccurs"=0) as actual parameters
        # ignore undefined values represented by `null`, empty list, or empty string
        if value or value in [0, 0.0]:
            if isinstance(value, list):
                json_io[field] = [_complex2format(v) if isinstance(v, ComplexData) else v for v in value]
            elif isinstance(value, ComplexData):
                json_io[field] = _complex2format(value)
            else:
                json_io[field] = value

    # add 'format' if missing, derived from other variants
    if "formats" not in json_io:
        for field in WPS_FIELD_FORMAT:
            fmt = _get_field(json_io, field, search_variations=True)
            if not fmt:
                continue
            if isinstance(fmt, dict):
                fmt = [fmt]
            fmt = filter(lambda f: isinstance(f, dict), fmt)
            if not isinstance(json_io.get("formats"), list):
                json_io["formats"] = list()
            for var_fmt in fmt:
                # add it only if not exclusively provided by a previous variant
                json_fmt_items = [j_fmt.items() for j_fmt in json_io["formats"]]
                if any(all(var_item in items for var_item in var_fmt.items()) for items in json_fmt_items):
                    continue
                json_io["formats"].append(var_fmt)

    return json_io


def _xml_wps2cwl(wps_process_response):
    # type: (requests.models.Response) -> Tuple[CWL, JSON]
    """
    Converts a `WPS-1 ProcessDescription XML` tree structure to an equivalent `WPS-2 Process JSON` and builds the
    associated `CWL` package in conformance to :ref:`weaver.processes.wps_package.CWL_REQUIREMENT_APP_WPS1`.

    :param wps_process_response: valid response (XML, 200) from a `WPS-1 ProcessDescription`.
    """
    def _tag_name(_xml):
        # type: (Union[XML, AnyStr]) -> AnyStr
        """Obtains ``tag`` from a ``{namespace}Tag`` `XML` element."""
        if hasattr(_xml, "tag"):
            _xml = _xml.tag
        return _xml.split('}')[-1].lower()

    # look for `XML` structure starting at `ProcessDescription` (WPS-1)
    xml_resp = lxml.etree.fromstring(wps_process_response.content)
    xml_wps_process = xml_resp.xpath("//ProcessDescription")  # type: List[XML]
    if not len(xml_wps_process) == 1:
        raise ValueError("Could not retrieve a valid 'ProcessDescription' from WPS-1 response.")
    process_id = None
    for sub_xml in xml_wps_process[0]:
        tn = _tag_name(sub_xml)
        if tn == "identifier":
            process_id = sub_xml.text
            break
    if not process_id:
        raise ValueError("Could not find a match for 'ProcessDescription.identifier' from WPS-1 response.")

    # transform WPS-1 -> WPS-2
    wps = WebProcessingService(wps_process_response.url)
    wps_service_url = urlparse(wps_process_response.url)
    if wps.provider:
        wps_service_name = wps.provider.name
    else:
        wps_service_name = wps_service_url.hostname
    process_info = {
        "identifier": "{}_{}".format(wps_service_name, process_id),
        "keywords": [wps_service_name],
    }
    wps_process = wps.describeprocess(process_id, xml=wps_process_response.content)
    for field in ["title", "abstract"]:
        process_info[field] = _get_field(wps_process, field, search_variations=True)
    if wps_process.metadata:
        process_info["metadata"] = []
    for meta in wps_process.metadata:
        process_info["metadata"].append({"href": meta.url, "title": meta.title, "role": meta.role})
    process_info["inputs"] = []     # type: List[JSON]
    process_info["outputs"] = []    # type: List[JSON]
    for wps_in in wps_process.dataInputs:       # type: OWS_Input_Type
        process_info["inputs"].append(_ows2json_io(wps_in))
    for wps_out in wps_process.processOutputs:  # type: OWS_Output_Type
        process_info["outputs"].append(_ows2json_io(wps_out))

    # generate CWL for WPS-1 using parsed WPS-2
    cwl_package = {
        "cwlVersion": "v1.0",
        "class": "CommandLineTool",
        "hints": {
            CWL_REQUIREMENT_APP_WPS1: {
                "provider": get_url_without_query(wps_service_url),
                "process": process_id,
            }
        },
        "inputs": {},
        "outputs": {},
    }
    for io_select in [WPS_INPUT, WPS_OUTPUT]:
        io_process = "{}s".format(io_select)
        for wps_io in process_info[io_process]:    # type: JSON
            wps_io_type = _get_field(wps_io, "type", search_variations=True)
            wps_io_id = _get_field(wps_io, "identifier", search_variations=True)
            if wps_io_type != "ComplexData":
                # special OWS-WPS types conversion to match ones allowed by CWL
                if wps_io_type in ["date", "time", "dateTime", "anyURI"]:
                    wps_io_type = "string"
                if wps_io_type in ["scale", "angle"]:
                    wps_io_type = "float"
                if wps_io_type in ["integer", "positiveInteger", "nonNegativeInteger"]:
                    wps_io_type = "int"
                wps_allow = _get_field(wps_io, "allowed_values", search_variations=True)
                if isinstance(wps_allow, list) and len(wps_allow) > 0:
                    cwl_package[io_process][wps_io_id] = {"type": {"type": "enum", "symbols": wps_allow}}
                else:
                    cwl_package[io_process][wps_io_id] = {"type": wps_io_type}
            else:
                wps_io_ext = "*"
                wps_io_fmt = DefaultFormat.mime_type
                for field in WPS_FIELD_FORMAT:
                    fmt = _get_field(wps_io, field, search_variations=True)
                    if isinstance(fmt, list) and len(fmt):
                        wps_io_fmt = wps_io[field][0]["mimeType"]
                        wps_io_ext = get_extension(wps_io_fmt)
                        break
                cwl_package[io_process][wps_io_id] = {"type": "File"}
                cwl_io_ref, cwl_io_fmt = get_cwl_file_format(wps_io_fmt)
                if cwl_io_ref and cwl_io_fmt:
                    cwl_package[io_process][wps_io_id]["format"] = cwl_io_fmt
                    if "$namespaces" not in cwl_package:
                        cwl_package["$namespaces"] = dict()
                    cwl_package["$namespaces"].update(cwl_io_ref)
                if io_select == WPS_OUTPUT:
                    # TODO:
                    #   - how to specify the 'name' part of the glob (using the "id" value for now)
                    #   - how to choose extension if there are multiple formats? (currently get first)
                    cwl_package[io_process][wps_io_id]["outputBinding"] = {
                        "glob": "{}.{}".format(wps_io_id, wps_io_ext)
                    }

            if io_select == WPS_INPUT:
                wps_default = _get_field(wps_io, "default", search_variations=True)
                wps_min_occ = _get_field(wps_io, "min_occurs", search_variations=True)
                if wps_default != null or wps_min_occ in [0, "0"]:
                    cwl_package[io_process][wps_io_id]["default"] = wps_default or "null"

            wps_max_occ = _get_field(wps_io, "max_occurs", search_variations=True)
            if wps_max_occ != null and wps_max_occ > 1:
                cwl_package[io_process][wps_io_id]["type"] = {
                    "type": "array",
                    "items": cwl_package[io_process][wps_io_id]["type"]
                }

    return cwl_package, process_info


def _generate_process_with_cwl_from_reference(reference):
    # type: (AnyStr) -> Tuple[CWL, JSON]
    """
    Resolves the ``reference`` type (`CWL`, `WPS-1`, `WPS-2`) and generates a `CWL` ``package`` from it.
    Additionally provides minimal process details retrieved from the ``reference``.
    """
    cwl_package = None
    process_info = dict()

    # match against direct CWL reference
    reference_path, reference_ext = os.path.splitext(reference)
    reference_name = os.path.split(reference_path)[-1]
    if reference_ext.replace('.', '') in PACKAGE_EXTENSIONS:
        cwl_package = _load_package_file(reference)
        process_info = {"identifier": reference_name}

    # match against WPS-1/2 reference
    else:
        response = requests.get(reference)
        if response.status_code != HTTPOk.code:
            raise HTTPServiceUnavailable("Couldn't obtain a valid response from [{}]. Service response: [{} {}]"
                                         .format(reference, response.status_code, response.reason))
        content_type = get_header("Content-Type", response.headers)
        if any(ct in content_type for ct in CONTENT_TYPE_ANY_XML):
            # attempt to retrieve a WPS-1 ProcessDescription definition
            cwl_package, process_info = _xml_wps2cwl(response)

        elif any(ct in content_type for ct in [CONTENT_TYPE_APP_JSON]):
            payload = response.json()
            # attempt to retrieve a WPS-2 Process definition, owsContext is expected in body
            if "process" in payload:
                process_info = payload["process"]
                ows_ref = process_info.get("owsContext", {}).get("offering", {}).get("content", {}).get("href")
                cwl_package = _load_package_file(ows_ref)
            # if somehow the CWL was referenced without an extension, handle it here
            # also handle parsed WPS-2 process description also with a reference
            elif "cwlVersion" in payload:
                cwl_package = _load_package_file(reference)
                process_info = {"identifier": reference_name}

    return cwl_package, process_info


def get_process_definition(process_offering, reference=None, package=None, data_source=None):
    # type: (JSON, Optional[AnyStr], Optional[CWL], Optional[AnyStr]) -> JSON
    """
    Returns an updated process definition dictionary ready for storage using provided `WPS` ``process_offering``
    and a package definition passed by ``reference`` or ``package`` `CWL` content.
    The returned process information can be used later on to load an instance of :class:`weaver.wps_package.WpsPackage`.

    :param process_offering: `WPS REST-API` (`WPS-2`) process offering as `JSON`.
    :param reference: URL to `CWL` package definition, `WPS-1 DescribeProcess` endpoint or `WPS-2 Process` endpoint.
    :param package: literal `CWL` package definition (`YAML` or `JSON` format).
    :param data_source: where to resolve process IDs (default: localhost if ``None``).
    :return: updated process definition with resolved/merged information from ``package``/``reference``.
    """

    def try_or_raise_package_error(call, reason):
        try:
            LOGGER.debug("Attempting: [{}].".format(reason))
            return call()
        except Exception as exc:
            # re-raise any exception already handled by a "package" error as is, but with a more detailed message
            # handle any other sub-exception that wasn't processed by a "package" error as a registration error
            package_errors = (PackageRegistrationError, PackageTypeError, PackageRegistrationError, PackageNotFound)
            exc_type = type(exc) if isinstance(exc, package_errors) else PackageRegistrationError
            LOGGER.exception(exc.message)
            raise exc_type(
                "Invalid package/reference definition. {0} generated error: [{1}].".format(reason, repr(exc))
            )

    if not (isinstance(package, dict) or isinstance(reference, six.string_types)):
        raise PackageRegistrationError(
            "Invalid parameters amongst one of [package, reference].")
    if package and reference:
        raise PackageRegistrationError(
            "Simultaneous parameters [package, reference] not allowed.")

    process_info = process_offering
    if reference:
        package, process_info = _generate_process_with_cwl_from_reference(reference)
        process_info.update(process_offering)   # override upstream details
    if not isinstance(package, dict):
        raise PackageRegistrationError("Cannot decode process package contents.")
    if "class" not in package:
        raise PackageRegistrationError("Cannot obtain process type from package class.")

    LOGGER.debug("Using data source: '{}'".format(data_source))
    package_factory, process_type, _ = try_or_raise_package_error(
        lambda: _load_package_content(package, data_source=data_source),
        reason="Loading package content")

    package_inputs, package_outputs = try_or_raise_package_error(
        lambda: _get_package_inputs_outputs(package_factory),
        reason="Definition of package/process inputs/outputs")
    process_inputs = process_info.get("inputs", list())
    process_outputs = process_info.get("outputs", list())

    try_or_raise_package_error(
        lambda: _update_package_metadata(process_info, package),
        reason="Metadata update")

    package_inputs, package_outputs = try_or_raise_package_error(
        lambda: _merge_package_inputs_outputs(process_inputs, package_inputs, process_outputs, package_outputs),
        reason="Merging of inputs/outputs")

    # obtain any retrieved process id if not already provided from upstream process offering, and clean it
    process_id = get_sane_name(get_any_id(process_info), assert_invalid=False)
    if not process_id:
        raise PackageRegistrationError("Could not retrieve any process identifier.")

    process_offering.update({
        "identifier": process_id,
        "package": package,
        "type": process_type,
        "inputs": package_inputs,
        "outputs": package_outputs
    })
    return process_offering


class WpsPackage(Process):
    package = None
    job_file = None
    log_file = None
    log_level = logging.INFO
    logger = None
    tmp_dir = None
    percent = None

    def __init__(self, **kw):
        """
        Creates a `WPS-2 Process` instance to execute a `CWL` package definition.

        Process parameters should be loaded from an existing :class:`weaver.datatype.Process`
        instance generated using :function:`weaver.wps_package.get_process_definition`.

        Provided ``kw`` should correspond to :method:`weaver.datatype.Process.params_wps`
        """
        self.payload = kw.pop("payload")
        self.package = kw.pop("package")
        if not self.package:
            raise PackageRegistrationError("Missing required package definition for package process.")
        if not isinstance(self.package, dict):
            raise PackageRegistrationError("Unknown parsing of package definition for package process.")

        inputs = kw.pop("inputs", [])

        # handle EOImage inputs
        inputs = opensearch.replace_inputs_describe_process(inputs=inputs, payload=self.payload)

        inputs = [_json2wps_io(i, WPS_INPUT) for i in inputs]
        outputs = [_json2wps_io(o, WPS_OUTPUT) for o in kw.pop("outputs", list())]
        metadata = [_json2wps_field(meta_kw, "metadata") for meta_kw in kw.pop("metadata", list())]

        super(WpsPackage, self).__init__(
            self._handler,
            inputs=inputs,
            outputs=outputs,
            metadata=metadata,
            store_supported=True,
            status_supported=True,
            **kw
        )

    def setup_logger(self):
        # file logger for output
        self.log_file = get_status_location_log_path(self.status_location)
        log_file_handler = logging.FileHandler(self.log_file)
        log_file_formatter = logging.Formatter(fmt=get_log_fmt(), datefmt=get_log_date_fmt())
        log_file_handler.setFormatter(log_file_formatter)

        # prepare package logger
        self.logger = logging.getLogger("wps_package.{}".format(self.package_id))
        self.logger.addHandler(log_file_handler)
        self.logger.setLevel(self.log_level)

        # add CWL job and CWL runner logging to current package logger
        job_logger = logging.getLogger("job {}".format(PACKAGE_DEFAULT_FILE_NAME))
        job_logger.addHandler(log_file_handler)
        job_logger.setLevel(self.log_level)
        cwl_logger = logging.getLogger("cwltool")
        cwl_logger.addHandler(log_file_handler)
        cwl_logger.setLevel(self.log_level)

        # add weaver Tweens logger to current package logger
        weaver_tweens_logger = logging.getLogger("weaver.tweens")
        weaver_tweens_logger.addHandler(log_file_handler)
        weaver_tweens_logger.setLevel(self.log_level)

    def update_status(self, message, progress, status):
        # type: (AnyStr, int, AnyStatusType) -> None
        """Updates the `PyWPS` real job status from a specified parameters."""
        self.percent = progress or self.percent or 0

        # find the enum PyWPS status matching the given one as string
        pywps_status = map_status(status, STATUS_COMPLIANT_PYWPS)
        pywps_status_id = STATUS_PYWPS_IDS[pywps_status]

        # pywps overrides 'status' by 'accepted' in 'update_status', so use the '_update_status' to enforce the status
        # using protected method also avoids weird overrides of progress percent on failure and final 'success' status
        # noinspection PyProtectedMember
        self.response._update_status(pywps_status_id, message, self.percent)
        self.log_message(status=status, message=message, progress=progress)

    def step_update_status(self, message, progress, start_step_progress, end_step_progress, step_name,
                           target_host, status):
        # type: (AnyStr, int, int, int, AnyStr, AnyValue, AnyStr) -> None
        self.update_status(
            message="{0} [{1}] - {2}".format(target_host, step_name, str(message).strip()),
            progress=self.map_progress(progress, start_step_progress, end_step_progress),
            status=status,
        )

    def log_message(self, status, message, progress=None, level=logging.INFO):
        message = get_job_log_msg(status=map_status(status), message=message, progress=progress)
        self.logger.log(level, message, exc_info=level > logging.INFO)

    def exception_message(self, exception_type, exception=None, message="no message"):
        exception_msg = " [{}]".format(repr(exception)) if isinstance(exception, Exception) else ""
        self.log_message(status=STATUS_EXCEPTION,
                         message="{0}: {1}{2}".format(exception_type.__name__, message, exception_msg),
                         level=logging.ERROR)
        return exception_type("{0}{1}".format(message, exception_msg))

    @staticmethod
    def map_progress(progress, range_min, range_max):
        # type: (Number, int, int) -> Number
        return range_min + (progress * (range_max - range_min)) / 100

    @classmethod
    def map_step_progress(cls, step_index, steps_total):
        return cls.map_progress(100 * step_index / steps_total, PACKAGE_PROGRESS_RUN_CWL, PACKAGE_PROGRESS_CWL_DONE)

    @staticmethod
    def make_location_input(input_location, input_type, input_definition):
        # type: (AnyStr, AnyStr, ComplexInput) -> JSON
        location = {"location": input_location, "class": input_type}
        if input_definition.data_format is not None and input_definition.data_format.mime_type:
            fmt = get_cwl_file_format(input_definition.data_format.mime_type, make_reference=True)
            if fmt is not None:
                location["format"] = fmt
        return location

    def _handler(self, request, response):
        # type: (WPSRequest, ExecuteResponse) -> ExecuteResponse
        LOGGER.debug("HOME=%s, Current Dir=%s", os.environ.get("HOME"), os.path.abspath(os.curdir))
        self.request = request
        self.response = response
        self.package_id = self.request.identifier

        try:
            try:
                self.setup_logger()
                # self.response.outputs[PACKAGE_LOG_FILE].file = self.log_file
                # self.response.outputs[PACKAGE_LOG_FILE].as_reference = True
                self.update_status("Preparing package logs done.", PACKAGE_PROGRESS_PREP_LOG, STATUS_RUNNING)
            except Exception as exc:
                raise self.exception_message(PackageExecutionError, exc, "Failed preparing package logging.")

            self.update_status("Launching package...", PACKAGE_PROGRESS_LAUNCHING, STATUS_RUNNING)

            settings = get_settings(app)
            if get_weaver_configuration(settings) == WEAVER_CONFIGURATION_EMS:
                # EMS dispatch the execution to the ADES
                loading_context = LoadingContext()
                loading_context.construct_tool_object = self.make_tool
            else:
                # ADES execute the cwl locally
                loading_context = None

            wps_out_dir_prefix = os.path.join(get_wps_output_dir(settings), "tmp")
            runtime_context = RuntimeContext(kwargs={
                "no_read_only": True, "outdir": self.workdir, "tmp_outdir_prefix": wps_out_dir_prefix})
            try:
                self.package_inst, _, self.step_packages = _load_package_content(self.package,
                                                                                 package_name=self.package_id,
                                                                                 # no data source for local package
                                                                                 data_source=None,
                                                                                 loading_context=loading_context,
                                                                                 runtime_context=runtime_context)
                self.step_launched = []

            except Exception as ex:
                raise PackageRegistrationError("Exception occurred on package instantiation: '{}'".format(repr(ex)))
            self.update_status("Loading package content done.", PACKAGE_PROGRESS_LOADING, STATUS_RUNNING)

            try:
                cwl_input_info = dict([(i["name"], i) for i in self.package_inst.t.inputs_record_schema["fields"]])
                self.update_status("Retrieve package inputs done.", PACKAGE_PROGRESS_GET_INPUT, STATUS_RUNNING)
            except Exception as exc:
                raise self.exception_message(PackageExecutionError, exc, "Failed retrieving package input types.")
            try:
                # identify EOImages from payload
                request.inputs = opensearch.get_original_collection_id(self.payload, request.inputs)
                eoimage_data_sources = opensearch.get_eo_images_data_sources(self.payload, request.inputs)
                if eoimage_data_sources:
                    accept_mime_types = opensearch.get_eo_images_mime_types(self.payload)
                    opensearch.insert_max_occurs(self.payload, request.inputs)
                    request.inputs = opensearch.query_eo_images_from_wps_inputs(request.inputs,
                                                                                eoimage_data_sources,
                                                                                accept_mime_types)

                cwl_inputs = dict()
                for input_id in request.inputs:
                    # skip empty inputs (if that is even possible...)
                    input_occurs = request.inputs[input_id]
                    if len(input_occurs) <= 0:
                        continue
                    # process single occurrences
                    input_i = input_occurs[0]
                    # handle as reference/data
                    is_array, elem_type = _is_cwl_array_type(cwl_input_info[input_id])
                    if is_array:
                        # extend array data that allow max_occur > 1
                        input_data = [i.url if i.as_reference else i.data for i in input_occurs]
                        input_type = elem_type
                    else:
                        input_data = input_i.url if input_i.as_reference else input_i.data
                        input_type = cwl_input_info[input_id]["type"]
                    if isinstance(input_i, ComplexInput) or elem_type == "File":
                        if isinstance(input_data, list):
                            cwl_inputs[input_id] = [self.make_location_input(data, input_type, input_def)
                                                    for data, input_def in zip(input_data, input_occurs)]
                        else:
                            cwl_inputs[input_id] = self.make_location_input(input_data, input_type, input_i)
                    elif isinstance(input_i, (LiteralInput, BoundingBoxInput)):
                        cwl_inputs[input_id] = input_data
                    else:
                        raise self.exception_message(
                            PackageTypeError, None, "Undefined package input for execution: {}.".format(type(input_i)))
                self.update_status("Convert package inputs done.", PACKAGE_PROGRESS_CONVERT_INPUT, STATUS_RUNNING)
            except Exception as exc:
                raise self.exception_message(PackageExecutionError, exc, "Failed to load package inputs.")

            try:
                self.update_status("Running package...", PACKAGE_PROGRESS_RUN_CWL, STATUS_RUNNING)

                # Inputs starting with file:// will be interpreted as ems local files
                # If OpenSearch obtain file:// references that must be passed to the ADES use an uri starting
                # with OPENSEARCH_LOCAL_FILE_SCHEME://
                LOGGER.debug("Launching process package with inputs:\n{}".format(cwl_inputs))
                result = self.package_inst(**cwl_inputs)
                self.update_status("Package execution done.", PACKAGE_PROGRESS_CWL_DONE, STATUS_RUNNING)
            except Exception as exc:
                raise self.exception_message(PackageExecutionError, exc, "Failed package execution.")
            try:
                for output in request.outputs:
                    # TODO: adjust output for glob patterns (https://github.com/crim-ca/weaver/issues/24)
                    if isinstance(result[output], list) and not isinstance(self.response.outputs[output], list):
                        result[output] = result[output][0]  # expect only one output
                    if "location" in result[output]:
                        self.response.outputs[output].as_reference = True
                        self.response.outputs[output].file = result[output]["location"].replace("file://", "")
                    else:
                        self.response.outputs[output].data = result[output]
                self.update_status("Generate package outputs done.", PACKAGE_PROGRESS_PREP_OUT, STATUS_RUNNING)
            except Exception as exc:
                raise self.exception_message(PackageExecutionError, exc, "Failed to save package outputs.")
        # noinspection PyBroadException
        except Exception:
            # return log file location by status message since outputs are not obtained by WPS failed process
            error_msg = "Package completed with errors. Server logs: {}".format(self.log_file)
            self.update_status(error_msg, self.percent, STATUS_FAILED)
            raise
        else:
            self.update_status("Package complete.", PACKAGE_PROGRESS_DONE, STATUS_SUCCEEDED)
        return self.response

    def make_tool(self, toolpath_object, loading_context):
        # type: (ToolPathObjectType, LoadingContext) -> ProcessCWL
        from weaver.processes.wps_workflow import default_make_tool
        return default_make_tool(toolpath_object, loading_context, self.get_job_process_definition)

    def get_job_process_definition(self, jobname, joborder, tool):
        # type: (AnyStr, JSON, CWL) -> WpsPackage
        """
        This function is called before running an ADES job (either from a workflow step or a simple EMS dispatch).
        It must return a WpsProcess instance configured with the proper package, ADES target and cookies.

        :param jobname: The workflow step or the package id that must be launch on an ADES :class:`string`
        :param joborder: The params for the job :class:`dict {input_name: input_value}`
                         input_value is one of `input_object` or `array [input_object]`
                         input_object is one of `string` or `dict {class: File, location: string}`
                         in our case input are expected to be File object
        :param tool: Whole `CWL` config including hints requirement
        """

        if jobname == self.package_id:
            # A step is the package itself only for non-workflow package being executed on the EMS
            # default action requires ADES dispatching but hints can indicate also WPS1 or ESGF-CWT provider
            step_payload = self.payload
            process = self.package_id
            jobtype = "package"
        else:
            # Here we got a step part of a workflow (self is the workflow package)
            step_payload = _get_process_payload(self.step_packages[jobname])
            process = self.step_packages[jobname]
            jobtype = "step"

        # Progress made with steps presumes that they are done sequentially and have the same progress weight
        start_step_progress = self.map_step_progress(len(self.step_launched), max(1, len(self.step_packages)))
        end_step_progress = self.map_step_progress(len(self.step_launched) + 1, max(1, len(self.step_packages)))

        self.step_launched.append(jobname)
        self.update_status("Preparing to launch {type} {name}.".format(type=jobtype, name=jobname),
                           start_step_progress, STATUS_RUNNING)

        def _update_status_dispatch(_provider, _message, _progress, _status):
            self.step_update_status(
                _message, _progress, start_step_progress, end_step_progress, jobname, _provider, _status
            )

        # package can define requirements and/or hints, if it's an application, only one is allowed, workflow can have
        # multiple, but they are not explicitly handled
        all_hints = list(dict(req) for req in tool.get("requirements", {}))
        all_hints.extend(dict(req) for req in tool.get("hints", {}))
        app_hints = filter(lambda h: any(h["class"].endswith(t) for t in CWL_REQUIREMENT_APP_TYPES), all_hints)
        if len(app_hints) > 1:
            raise ValueError("Package 'requirements' and/or 'hints' define too many conflicting values: {}, "
                             "only one permitted amongst {}.".format(list(app_hints), list(CWL_REQUIREMENT_APP_TYPES)))
        requirement = app_hints[0] if app_hints else {"class": ""}
        if requirement["class"].endswith(CWL_REQUIREMENT_APP_WPS1):
            req_params = ["provider", "process"]
            if not all(r in requirement for r in ["provider", "process"]):
                raise ValueError("Missing requirement [{}] details amongst {}".format(requirement["class"], req_params))
            provider = requirement["provider"]
            # The process id of the provider isn't required to be the same as the one use in the EMS
            process = requirement["process"]
            from weaver.processes.wps1_process import Wps1Process
            return Wps1Process(provider=provider,
                               process=process,
                               request=self.request,
                               update_status=_update_status_dispatch)
        elif requirement["class"].endswith(CWL_REQUIREMENT_APP_ESGF_CWT):
            req_params = ["provider", "process"]
            if not all(r in requirement for r in ["provider", "process"]):
                raise ValueError("Missing requirement [{}] details amongst {}".format(requirement["class"], req_params))
            provider = requirement["provider"]
            # The process id of the provider isn't required to be the same as the one use in the EMS
            process = requirement["process"]
            from weaver.processes.esgf_process import ESGFProcess
            return ESGFProcess(provider=provider,
                               process=process,
                               request=self.request,
                               update_status=_update_status_dispatch)
        else:
            # implements both `PROCESS_APPLICATION` with `CWL_REQUIREMENT_APP_DOCKER` and `PROCESS_WORKFLOW`
            from weaver.processes.wps3_process import Wps3Process
            return Wps3Process(step_payload=step_payload,
                               joborder=joborder,
                               process=process,
                               request=self.request,
                               update_status=_update_status_dispatch)