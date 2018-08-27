import os
import cwltool
import cwltool.factory
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
from pywps.response.status import WPS_STATUS
from pywps.inout.literaltypes import AnyValue
from pywps.validator.mode import MODE
from pywps.app.Common import Metadata
from twitcher.utils import parse_request_query
from twitcher.exceptions import WorkflowTypeError, WorkflowRegistrationError, WorkflowExecutionError
from collections import OrderedDict
import json
import yaml
import tempfile
import shutil

import logging
LOGGER = logging.getLogger("PYWPS")


WORKFLOW_EXTENSIONS = frozenset(['yaml', 'yml', 'json', 'cwl', 'job'])
WORKFLOW_LITERAL_TYPES = frozenset(['string', 'boolean', 'float', 'int', 'integer', 'long', 'double', 'null', 'Any'])
WORKFLOW_CUSTOM_TYPES = frozenset(['enum'])  # can be anything, but support 'enum' which is more common
WORKFLOW_FILE_NAME = 'workflow.cwl'
WORKFLOW_LOG_FILE = 'workflow_log_file'


def check_workflow_file(cwl_file):
    cwl_path = os.path.abspath(cwl_file)
    file_ext = os.path.splitext(cwl_path)[1].replace('.', '')
    if file_ext not in WORKFLOW_EXTENSIONS:
        raise WorkflowRegistrationError("Not a valid CWL file type: `{}`.".format(file_ext))
    if not os.path.isfile(cwl_path):
        raise WorkflowRegistrationError("Cannot find CWL file at: `{}`.".format(cwl_path))
    return cwl_path


def load_workflow_file(file_path):
    file_path = check_workflow_file(file_path)
    # yaml properly loads json as well
    with open(file_path, 'r') as f:
        return yaml.safe_load(f)


def load_workflow_content(workflow_dict):
    # TODO: find how to pass dict directly (?) instead of dump to tmp file
    tmp_dir = tempfile.mkdtemp()
    tmp_json_cwl = os.path.join(tmp_dir, WORKFLOW_FILE_NAME)
    with open(tmp_json_cwl, 'w') as f:
        json.dump(workflow_dict, f)
    cwl_factory = cwltool.factory.Factory()
    workflow = cwl_factory.make(tmp_json_cwl)
    shutil.rmtree(tmp_dir)
    return workflow


def _cwl2wps_io(io_info):
    """Converts input/output parameters from CWL types to WPS types.
    :param io_info: parsed IO of a CWL file
    :return: corresponding IO in WPS format
    """
    is_input = False
    is_output = False
    if 'inputBinding' in io_info:
        is_input = True
        io_literal = LiteralInput
        io_complex = ComplexInput
        io_bbox = BoundingBoxInput
    elif 'outputBinding' in io_info:
        is_output = True
        io_literal = LiteralOutput
        io_complex = ComplexOutput
        io_bbox = BoundingBoxOutput
    else:
        raise WorkflowTypeError("Unsupported I/O info definition: `{}`.".format(repr(io_info)))

    io_name = io_info['name']
    io_type = io_info['type']

    # literal types
    if io_type in WORKFLOW_LITERAL_TYPES or io_type in WORKFLOW_CUSTOM_TYPES:
        io_mode = MODE.NONE
        io_allow = AnyValue
        if io_type == 'Any':
            io_type = 'anyvalue'
        if io_type == 'null':
            io_type = 'novalue'
        if io_type in ['int', 'integer']:
            io_type = 'integer'
        if io_type in ['float', 'long', 'double']:
            io_type = 'float'
        if io_type in WORKFLOW_CUSTOM_TYPES:
            io_type = 'string'
            io_mode = MODE.SIMPLE
            io_allow = io_info['symbols']
        return io_literal(identifier=io_name,
                          title=io_info.get('label', io_name),
                          abstract=io_info.get('doc', ''),
                          data_type=io_type,
                          default=io_info.get('default', None),
                          min_occurs=1, max_occurs=1,
                          # unless extended by custom types, no value validation for literals
                          mode=io_mode,
                          allowed_values=io_allow)
    # complex types
    else:
        kw = {
            'identifier': io_name,
            'title': io_info.get('label', io_name),
            'abstract': io_info.get('doc', ''),
        }
        if 'format' in io_info:
            kw['supported_formats'] = [Format(io_info['format'])]
            kw['mode'] = MODE.SIMPLE
        else:
            # we need to minimally add 1 format, otherwise empty list is evaluated as None by pywps
            # when 'supported_formats' is None, the process's json property raises because of it cannot iterate formats
            kw['supported_formats'] = [Format('text/plain')]
            kw['mode'] = MODE.NONE
        if is_output:
            if io_type == 'Directory':
                kw['as_reference'] = True
            if io_type == 'File':
                has_contents = io_info.get('contents') is not None
                kw['as_reference'] = False if has_contents else True
        return io_complex(**kw)


def _dict2wps_io(io_info, input_or_output):
    """Converts input/output parameters from a JSON dict to WPS types.
    :param io_info: IO in JSON dict format
    :param input_or_output: 'input' or 'output' to specified desired WPS type conversion.
    :return: corresponding IO in WPS format
    """
    # remove extra fields added by pywps
    io_info.pop('workdir', None)
    io_info.pop('any_value', None)
    io_info.pop('data_format', None)
    io_info.pop('data', None)
    io_info.pop('file', None)

    # convert sub-format objects
    formats = io_info.pop('supported_formats', None)
    if formats is not None:
        io_info['supported_formats'] = [Format(**fmt) for fmt in formats]

    # convert by type
    io_type = io_info.pop('type', 'complex')    # only ComplexOutput doesn't have 'type'
    if input_or_output == 'input':
        if io_type == 'complex':
            return ComplexInput(**io_info)
        if io_type == 'bbox':
            return BoundingBoxInput(**io_info)
        if io_type == 'literal':
            return LiteralInput(**io_info)
    elif input_or_output == 'output':
        # extra params to remove for outputs
        io_info.pop('min_occurs', None)
        io_info.pop('max_occurs', None)
        if io_type == 'complex':
            return ComplexOutput(**io_info)
        if io_type == 'bbox':
            return BoundingBoxOutput(**io_info)
        if io_type == 'literal':
            return LiteralOutput(**io_info)
    raise WorkflowTypeError("Unknown conversion from dict to WPS type (type={0}, mode={1})."
                            .format(io_type, input_or_output))


def _get_field(io_object, field):
    if isinstance(io_object, dict):
        return io_object.get(field, None)
    return getattr(io_object, field, None)


def _set_field(io_object, field, value):
    if isinstance(io_object, dict):
        io_object[field] = value
        return
    setattr(io_object, field, None)


def _merge_workflow_io(wps_io_list, cwl_io_list):
    """
    Update I/O definitions to use for process creation and returned by GetCapabilities, DescribeProcess.
    If WPS I/O definitions where provided during deployment, update them with CWL-to-WPS converted I/O and
    preserve their optional WPS fields. Otherwise, provided minimum field requirements from CWL.
    Adds and removes any deployment WPS I/O definitions that don't match any CWL I/O by id.

    :param wps_io_list: list of WPS I/O passed during process deployment.
    :param cwl_io_list: list of CWL I/O converted to WPS-like I/O for counter-validation.
    :returns: list of validated/updated WPS I/O for the process.
    """
    if not isinstance(cwl_io_list, list):
        raise WorkflowTypeError("CWL I/O definitions must be provided, empty list if none required.")
    if not wps_io_list:
        wps_io_list = list()
    wps_io_dict = OrderedDict((_get_field(wps_io, 'identifier'), wps_io) for wps_io in wps_io_list)
    cwl_io_dict = OrderedDict((_get_field(cwl_io, 'identifier'), cwl_io) for cwl_io in cwl_io_list)
    missing_io_list = set(cwl_io_dict) - set(wps_io_dict)
    updated_io_list = list()
    for cwl_id in missing_io_list:
        updated_io_list.append(cwl_io_dict[cwl_id])
    for wps_io in wps_io_list:
        wps_id = _get_field(wps_io, 'identifier')
        # WPS I/O by id not matching CWL I/O are discarded
        if wps_id in wps_io_dict:
            # retrieve any additional fields (metadata, keywords, etc.) passed as input,
            # but override CWL-converted types and formats
            if _get_field(wps_io, 'data_type') is not None:
                _set_field(wps_io, 'data_type', _get_field(cwl_io_dict[wps_id], 'data_type'))
            updated_io_list.append(wps_io)
    return updated_io_list


def merge_workflow_inputs_outputs(wps_inputs_list, cwl_inputs_list, wps_outputs_list, cwl_outputs_list, as_json=False):
    """Merges I/O definitions to use for process creation and returned by GetCapabilities, DescribeProcess
    using the WPS specifications (from request POST) and CWL specifications (extracted from file)."""
    wps_inputs = _merge_workflow_io(wps_inputs_list, cwl_inputs_list)
    wps_outputs = _merge_workflow_io(wps_outputs_list, cwl_outputs_list)
    if as_json:
        return [i.json for i in wps_inputs], [o.json for o in wps_outputs]
    return wps_inputs, wps_outputs


def _get_workflow_io(workflow, io_attrib, as_json):
    cwl_workflow_io = getattr(workflow.t, io_attrib)
    wps_workflow_io = [_cwl2wps_io(io) for io in cwl_workflow_io['fields']]
    if as_json:
        return [io.json for io in wps_workflow_io]
    return wps_workflow_io


def get_workflow_inputs(workflow, as_json=False):
    """Generates WPS-like inputs using parsed CWL workflow input definitions."""
    return _get_workflow_io(workflow, io_attrib='inputs_record_schema', as_json=as_json)


def get_workflow_outputs(workflow, as_json=False):
    """Generates WPS-like outputs using parsed CWL workflow output definitions."""
    return _get_workflow_io(workflow, io_attrib='outputs_record_schema', as_json=as_json)


def get_workflow_inputs_outputs(workflow, as_json=False):
    """Generates WPS-like (inputs,outputs) tuple using parsed CWL workflow output definitions."""
    return _get_workflow_io(workflow, io_attrib='inputs_record_schema', as_json=as_json), \
           _get_workflow_io(workflow, io_attrib='outputs_record_schema', as_json=as_json)


class Workflow(Process):
    workflow = None
    job_file = None
    log_file = None
    log_level = logging.INFO
    logger = None
    tmp_dir = None
    percent = None

    def __init__(self, **kw):
        package = kw.pop('package')
        if not package:
            raise WorkflowRegistrationError("Missing required package definition for workflow process.")
        if isinstance(package, dict):
            self.workflow = load_workflow_content(package)
        else:
            raise WorkflowTypeError("Unknown parsing of package definition for workflow process.")

        wps_inputs = kw.pop('inputs')
        wps_outputs = kw.pop('outputs')
        cwl_inputs = get_workflow_inputs(self.workflow)
        cwl_outputs = get_workflow_outputs(self.workflow)
        inputs = [_dict2wps_io(i, 'input') for i in _merge_workflow_io(wps_inputs, cwl_inputs)]
        outputs = [_dict2wps_io(o, 'output') for o in _merge_workflow_io(wps_outputs, cwl_outputs)]

        # append a log output
        #outputs.append(ComplexOutput(WORKFLOW_LOG_FILE, 'Workflow log file',
        #                             as_reference=True, supported_formats=[Format('text/plain')]))

        super(Workflow, self).__init__(
            self._handler,
            inputs=inputs,
            outputs=outputs,
            store_supported=True,
            status_supported=True,
            **kw
        )

    def setup_logger(self):
        # file logger for output
        self.log_file = os.path.abspath(os.path.join(tempfile.mkdtemp(), '{}.log'.format(self.workflow_id)))
        log_file_handler = logging.FileHandler(self.log_file)
        log_file_formatter = logging.Formatter('%(asctime)s [%(name)s] %(levelname)s %(message)s')
        log_file_handler.setFormatter(log_file_formatter)

        # prepare workflow logger
        self.logger = logging.getLogger('wps_workflow.{}'.format(self.workflow_id))
        self.logger.addHandler(log_file_handler)
        self.logger.setLevel(self.log_level)

        # add CWL job and CWL runner logging to current workflow logger
        job_logger = logging.getLogger('job {}'.format(WORKFLOW_FILE_NAME))
        job_logger.addHandler(log_file_handler)
        job_logger.setLevel(self.log_level)
        cwl_logger = logging.getLogger('cwltool')
        cwl_logger.addHandler(log_file_handler)
        cwl_logger.setLevel(self.log_level)

    def update_status(self, message, progress=None, status=WPS_STATUS.STARTED):
        self.percent = progress or self.percent or 0
        # pywps overrides 'status' by 'accepted' in 'update_status', so use the '_update_status' to enforce the status
        # using the protected method also avoids weird overrides of progress % on failure and final 'success' status
        self.response._update_status(status, message, self.percent)
        self.log_message(message)

    def log_message(self, message, level=logging.INFO):
        self.logger.log(level, message, exc_info=level > logging.INFO)

    def exception_message(self, exception_type, exception=None, message='no message'):
        exception_msg = ' [{}]'.format(repr(exception)) if isinstance(exception, Exception) else ''
        self.log_message('{0}: {1}{2}'.format(exception_type.__name__, message, exception_msg), logging.ERROR)
        return exception_type('{0}{1}'.format(message, exception_msg))

    def _handler(self, request, response):
        LOGGER.debug("HOME=%s, Current Dir=%s", os.environ.get('HOME'), os.path.abspath(os.curdir))
        self.request = request
        self.response = response
        self.workflow_id = self.request.identifier

        try:
            try:
                self.setup_logger()
                #self.response.outputs[WORKFLOW_LOG_FILE].file = self.log_file
                #self.response.outputs[WORKFLOW_LOG_FILE].as_reference = True
                self.update_status("Preparing workflow logs done.", 1)
            except Exception as exc:
                raise self.exception_message(WorkflowExecutionError, exc, "Failed preparing workflow logging.")

            self.log_message("Workflow: {}".format(request.identifier))
            self.update_status("Launching workflow ...", 2)

            try:
                cwl_input_types = dict([(i['name'], i['type']) for i in self.workflow.t.inputs_record_schema['fields']])
                self.update_status("Parsing workflow inputs done.", 3)
            except Exception as exc:
                raise self.exception_message(WorkflowExecutionError, exc, "Failed retrieving workflow input types.")
            try:
                cwl_inputs = dict()
                for i in request.inputs.values():
                    i = i[0]  # only 1 input per deque since min/max=1
                    if isinstance(i, (LiteralInput, BoundingBoxInput)):
                        cwl_inputs[i.identifier] = i.data
                    elif isinstance(i, ComplexInput):
                        cwl_inputs[i.identifier] = {'location': i.data, 'class': cwl_input_types[i.identifier]}
                    else:
                        raise self.exception_message(WorkflowTypeError, None,
                                                     "Undefined workflow input for execution: {}.".format(type(i)))
                self.update_status("Convert workflow inputs done.", 4)
            except Exception as exc:
                raise self.exception_message(WorkflowExecutionError, exc, "Failed to load workflow inputs.")
            try:
                self.update_status("Running workflow ...", 6)
                result = self.workflow(**cwl_inputs)
                self.update_status("Workflow execution done.", 95)
            except Exception as exc:
                raise self.exception_message(WorkflowExecutionError, exc, "Failed workflow execution.")
            try:
                for output in request.outputs:
                    self.response.outputs[output].data = result[output]
                self.update_status("Generate workflow outputs done.", 99)
            except Exception as exc:
                raise self.exception_message(WorkflowExecutionError, exc, "Failed to save workflow outputs.")
        except:
            # return log file location by status message since outputs are not obtained by WPS failed process
            error_msg = "Workflow completed with errors. Server logs: {}".format(self.log_file)
            self.update_status(error_msg, status=WPS_STATUS.FAILED)
        else:
            self.update_status("Workflow complete.", 100, status=WPS_STATUS.SUCCEEDED)
        return self.response
