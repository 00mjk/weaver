import re
import time
from os.path import join

from typing import AnyStr, TYPE_CHECKING
import logging
import requests
import cwt

from weaver.status import STATUS_RUNNING, STATUS_SUCCEEDED, STATUS_FAILED
from weaver.processes.wps1_process import Wps1Process

if TYPE_CHECKING:
    from weaver.typedefs import JsonBody
    from typing import AnyStr, Dict, List, Tuple

LOGGER = logging.getLogger(__name__)


class Percent:
    PREPARING = 2
    SENDING = 3
    COMPUTE_DONE = 98
    FINISHED = 100


class ESGFProcess(Wps1Process):
    required_inputs = ("api_key", "variable")

    def execute(self, workflow_inputs, output_dir, expected_outputs):
        # type: (JsonBody, AnyStr, Dict[AnyStr, AnyStr]) -> None
        """Execute an ESGF process from cwl inputs"""
        LOGGER.debug("Executing ESGF process {}".format(self.process))

        inputs = self._prepare_inputs(workflow_inputs)
        api_key = self._get_api_key(workflow_inputs)
        esgf_process = self._run_process(inputs, api_key)
        self._process_results(esgf_process, output_dir, expected_outputs)

    def _prepare_inputs(self, workflow_inputs):
        # type: (JsonBody) -> List[cwt.Variable]
        """Convert inputs from cwl inputs to ESGF format"""
        message = "Preparing execute request for remote ESGF provider."
        self.update_status(message, Percent.PREPARING, STATUS_RUNNING)

        LOGGER.debug("Parsing inputs")

        self._check_required_inputs(workflow_inputs)
        files = self._get_files(workflow_inputs)

        LOGGER.debug("Creating esgf-compute-api inputs")

        inputs = [cwt.Variable(url, varname) for url, varname in files]

        return inputs

    def _check_required_inputs(self, workflow_inputs):
        for required_input in self.required_inputs:
            if required_input not in workflow_inputs:
                raise ValueError("Missing required input: {}".format(required_input))

    def _get_files(self, workflow_inputs):
        # type: (JsonBody) -> List[Tuple[str, str]]
        """Get all netcdf files from the cwl inputs"""
        return [("url", "tas")]

    def _get_api_key(self, workflow_inputs):
        # type: (JsonBody) -> str
        """Get the ESGF api key from the cwl inputs"""
        return "jfiep2319jfeipoq93021j9"

    def _run_process(self, inputs, api_key):
        # type: (List[cwt.Variable], str) -> cwt.Process
        """Run an ESGF process"""
        LOGGER.debug("Connecting to ESGF WPS")

        wps = cwt.WPSClient(self.provider, api_key=api_key, verify=False)
        process = wps.processes(self.process)[0]

        message = "Sending request."
        LOGGER.debug(message)
        self.update_status(message, Percent.SENDING, STATUS_RUNNING)

        wps.execute(process, inputs=inputs)

        LOGGER.debug("Waiting for result")

        self._wait(process)

        return process

    def _wait(self, esgf_process, sleep_time=2):
        # type: (cwt.Process, float) -> bool
        """Wait for an ESGF process to finish, while reporting its status"""
        status_history = set()

        status_percent = None
        last_percent_regex = re.compile(r".+ (\d{1,3})$")

        def update_history():
            global status_percent

            status = esgf_process.status

            if status not in status_history:
                match = last_percent_regex.match(status)
                if match:
                    status_percent = int(match.group(1))
                status_percent = max(Percent.SENDING, status_percent)

                status_history.add(status)

                message = "ESGF status: " + status
                LOGGER.debug(message)
                self.update_status(message, status_percent, STATUS_RUNNING)

        update_history()

        while esgf_process.processing:
            update_history()
            time.sleep(sleep_time)

        update_history()

        return esgf_process.succeeded

    def _process_results(self, esgf_process, output_dir, expected_outputs):
        # type: (cwt.Process, AnyStr, Dict[AnyStr, AnyStr])
        """Process the result of the execution"""
        if not esgf_process.succeeded:
            message = "Process failed."
            LOGGER.debug(message)
            self.update_status(message, Percent.FINISHED, STATUS_FAILED)
            return

        message = "Process successful."
        LOGGER.debug(message)
        self.update_status(message, Percent.COMPUTE_DONE, STATUS_RUNNING)
        try:
            self._write_outputs(esgf_process.output.uri, output_dir, expected_outputs)
        except Exception:
            message = "Error while downloading files."
            LOGGER.exception(message)
            self.update_status(message, Percent.FINISHED, STATUS_FAILED)
            raise

    def _write_outputs(self, uri, output_dir, expected_outputs):
        """Write the output netcdf url to a local drive"""
        message = "Downloading outputs."
        LOGGER.debug(message)
        self.update_status(message, Percent.COMPUTE_DONE, STATUS_RUNNING)

        nc_outputs = [v for v in expected_outputs.values() if v.lower().endswith(".nc")]
        if len(nc_outputs) > 1:
            raise NotImplemented("Multiple outputs are not implemented")

        # Todo: We should return the url instead of downloading...
        #       Maybe downloading could be a workflow step?

        LOGGER.debug("Downloading file: {}".format(uri))
        r = requests.get(uri, allow_redirects=True, stream=True)
        output_file = nc_outputs[0]

        # Fixme: This won't download a netcdf file...
        with open(join(output_dir, output_file), "wb") as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)

        message = "Download successful."
        LOGGER.debug(message)
        self.update_status(message, Percent.FINISHED, STATUS_SUCCEEDED)