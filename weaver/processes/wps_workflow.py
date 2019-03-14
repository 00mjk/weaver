from weaver.processes.builtin import BuiltinProcess
from weaver.processes.constants import (
    CWL_REQUIREMENT_APP_BUILTIN, CWL_REQUIREMENT_APP_DOCKER, CWL_REQUIREMENT_APP_WPS1, CWL_REQUIREMENT_APP_ESGF_CWT
)
from weaver.utils import now, get_settings
from weaver.wps import get_wps_output_dir
from cwltool import command_line_tool
from cwltool.process import stageFiles
from cwltool.provenance import CreateProvProfile
from cwltool.builder import (CONTENT_LIMIT, Builder, substitute)
from cwltool.errors import WorkflowException
from cwltool.job import JobBase, relink_initialworkdir
from cwltool.pathmapper import adjustDirObjs, adjustFileObjs, get_listing, trim_listing, visit_class
from cwltool.process import (Process as ProcessCWL, compute_checksums, normalizeFilesDirs,
                             shortname, uniquename, supportedProcessRequirements)
from cwltool.stdfsaccess import StdFsAccess
from cwltool.utils import (aslist, json_dumps, onWindows, bytes2str_in_dicts)
from cwltool.context import (LoadingContext, RuntimeContext, getdefault)
from cwltool.workflow import Workflow
from pyramid_celery import celery_app as app
from functools import cmp_to_key, partial
from schema_salad import validate
from schema_salad.sourceline import SourceLine
from six import string_types
import hashlib
import json
import locale
import logging
import os
import shutil
import tempfile
from typing import MutableMapping, Callable, cast, Text, TYPE_CHECKING  # these are actually used in the code
if TYPE_CHECKING:
    from weaver.typedefs import ExpectedOutputType, GetJobProcessDefinitionFunction, ToolPathObjectType, AnyValue
    from weaver.processes.wps_process_base import WpsProcessInterface
    from typing import Any, Dict, Generator, List, Optional, Set, Union
    from cwltool.command_line_tool import OutputPorts

LOGGER = logging.getLogger(__name__)
DEFAULT_TMP_PREFIX = "tmp"

# TODO: The code started as a copy of the class cwltool/command_line_tool.py,
#       and still has useless code in the context of a WPS workflow

# Extend the supported process requirements
supportedProcessRequirements += [
    CWL_REQUIREMENT_APP_BUILTIN,
    CWL_REQUIREMENT_APP_WPS1,
    CWL_REQUIREMENT_APP_ESGF_CWT,
]


def default_make_tool(toolpath_object,              # type: ToolPathObjectType
                      loading_context,              # type: LoadingContext
                      get_job_process_definition,   # type: GetJobProcessDefinitionFunction
                      ):                            # type: (...) -> ProcessCWL
    if not isinstance(toolpath_object, MutableMapping):
        raise WorkflowException(u"Not a dict: '%s'" % toolpath_object)
    if "class" in toolpath_object:
        if toolpath_object["class"] == "CommandLineTool":
            builtin_process_hints = [h.get("process") for h in toolpath_object.get("hints")
                                     if h.get("class", "").endswith(CWL_REQUIREMENT_APP_BUILTIN)]
            if len(builtin_process_hints) == 1:
                return BuiltinProcess(toolpath_object, loading_context)
            return WpsWorkflow(toolpath_object, loading_context, get_job_process_definition)
        if toolpath_object["class"] == "ExpressionTool":
            return command_line_tool.ExpressionTool(toolpath_object, loading_context)
        if toolpath_object["class"] == "Workflow":
            return Workflow(toolpath_object, loading_context)

    raise WorkflowException(
        u"Missing or invalid 'class' field in %s, expecting one of: CommandLineTool, ExpressionTool, Workflow" %
        toolpath_object["id"])


class CallbackJob(object):
    def __init__(self, job, output_callback, cachebuilder, jobcache):
        # type: (WpsWorkflow, Callable[[Any, Any], Any], Builder, Text) -> None
        self.job = job
        self.output_callback = output_callback
        self.cache_builder = cachebuilder
        self.output_dir = jobcache
        self.prov_obj = None  # type: Optional[CreateProvProfile]

    def run(self, loading_context):
        # type: (RuntimeContext) -> None
        self.output_callback(self.job.collect_output_ports(
            self.job.tool["outputs"],
            self.cache_builder,
            self.output_dir,
            getdefault(loading_context.compute_checksum, True)), "success")


# noinspection PyPep8Naming
class WpsWorkflow(ProcessCWL):
    def __init__(self, toolpath_object, loading_context, get_job_process_definition):
        # type: (Dict[Text, Any], LoadingContext, GetJobProcessDefinitionFunction) -> None
        super(WpsWorkflow, self).__init__(toolpath_object, loading_context)
        self.prov_obj = loading_context.prov_obj
        self.get_job_process_definition = get_job_process_definition

        # DockerRequirement is removed because we use our custom job which dispatch the processing to an ADES instead
        self.requirements = list(filter(lambda req: req["class"] != CWL_REQUIREMENT_APP_DOCKER, self.requirements))
        self.hints = list(filter(lambda req: req["class"] != CWL_REQUIREMENT_APP_DOCKER, self.hints))

    def job(self,
            joborder,           # type: Dict[Text, AnyValue]
            output_callbacks,   # type: Callable[[Any, Any], Any]
            runtimeContext,     # type: RuntimeContext
            ):                  # type: (...) -> Generator[Union[JobBase, CallbackJob], None, None]
        """
        Workflow job generator.

        :param joborder: inputs of the job submission
        :param output_callbacks: method to fetch step outputs and corresponding step details
        :param runtimeContext: configs about execution environment
        :return:
        """
        require_prefix = ""
        if self.metadata["cwlVersion"] == "v1.0":
            require_prefix = "http://commonwl.org/cwltool#"

        jobname = uniquename(runtimeContext.name or shortname(self.tool.get("id", "job")))

        # outdir must be served by the EMS because downstream step will need access to upstream steps output
        weaver_out_dir = get_wps_output_dir(get_settings(app))
        runtimeContext.outdir = tempfile.mkdtemp(
            prefix=getdefault(runtimeContext.tmp_outdir_prefix, DEFAULT_TMP_PREFIX),
            dir=weaver_out_dir)
        builder = self._init_job(joborder, runtimeContext)

        # `jobname` is the step name and `joborder` is the actual step inputs
        wps_workflow_job = WpsWorkflowJob(builder, builder.job, self.requirements, self.hints, jobname,
                                          self.get_job_process_definition(jobname, joborder, self.tool),
                                          self.tool["outputs"])
        wps_workflow_job.prov_obj = self.prov_obj
        wps_workflow_job.successCodes = self.tool.get("successCodes")
        wps_workflow_job.temporaryFailCodes = self.tool.get("temporaryFailCodes")
        wps_workflow_job.permanentFailCodes = self.tool.get("permanentFailCodes")

        # TODO Taken from command_line_tool.py maybe this could let us use the revmap if required at all
        # reffiles = copy.deepcopy(builder.files)
        # builder.pathmapper = self.make_path_mapper(
        #     reffiles, builder.stagedir, runtimeContext, True)
        # builder.requirements = wps_workflow_job.requirements

        wps_workflow_job.outdir = builder.outdir
        wps_workflow_job.tmpdir = builder.tmpdir
        wps_workflow_job.stagedir = builder.stagedir

        readers = {}  # type: Dict[Text, Any]
        timelimit = self.get_requirement(require_prefix + "TimeLimit")[0]
        if timelimit:
            with SourceLine(timelimit, "timelimit", validate.ValidationException):
                wps_workflow_job.timelimit = builder.do_eval(timelimit["timelimit"])
                if not isinstance(wps_workflow_job.timelimit, int) or wps_workflow_job.timelimit < 0:
                    raise Exception("timelimit must be an integer >= 0, got: %s" % wps_workflow_job.timelimit)

        wps_workflow_job.collect_outputs = partial(
            self.collect_output_ports, self.tool["outputs"], builder,
            compute_checksum=getdefault(runtimeContext.compute_checksum, True),
            jobname=jobname,
            readers=readers)
        wps_workflow_job.output_callback = output_callbacks

        yield wps_workflow_job

    def collect_output_ports(self,
                             ports,                  # type: Set[Dict[Text, Any]]
                             builder,                # type: Builder
                             outdir,                 # type: Text
                             compute_checksum=True,  # type: bool
                             jobname="",             # type: Text
                             readers=None            # type: Dict[Text, Any]
                             ):                      # type: (...) -> OutputPorts
        ret = {}  # type: OutputPorts
        debug = LOGGER.isEnabledFor(logging.DEBUG)
        try:
            fs_access = builder.make_fs_access(outdir)
            custom_output = fs_access.join(outdir, "cwl.output.json")
            if fs_access.exists(custom_output):
                with fs_access.open(custom_output, 'r') as f:
                    ret = json.load(f)
                if debug:
                    LOGGER.debug(u"Raw output from %s: %s", custom_output, json_dumps(ret, indent=4))
            else:
                for i, port in enumerate(ports):
                    def makeWorkflowException(msg):
                        return WorkflowException(
                            u"Error collecting output for parameter '%s':\n%s"
                            % (shortname(port["id"]), msg))
                    with SourceLine(ports, i, makeWorkflowException, debug):
                        fragment = shortname(port["id"])
                        ret[fragment] = self.collect_output(port, builder, outdir, fs_access,
                                                            compute_checksum=compute_checksum)
            if ret:
                # revmap = partial(command_line_tool.revmap_file, builder, outdir)
                adjustDirObjs(ret, trim_listing)

                # TODO: Attempt to avoid a crash because the revmap fct is not functional
                #       (intend for a docker usage only?)
                # visit_class(ret, ("File", "Directory"), cast(Callable[[Any], Any], revmap))
                visit_class(ret, ("File", "Directory"), command_line_tool.remove_path)
                normalizeFilesDirs(ret)
                visit_class(ret, ("File", "Directory"), partial(command_line_tool.check_valid_locations, fs_access))

                if compute_checksum:
                    adjustFileObjs(ret, partial(compute_checksums, fs_access))

            validate.validate_ex(
                self.names.get_name("outputs_record_schema", ""), ret,
                strict=False, logger=LOGGER)
            if ret is not None and builder.mutation_manager is not None:
                adjustFileObjs(ret, builder.mutation_manager.set_generation)
            return ret if ret is not None else {}
        except validate.ValidationException as e:
            raise WorkflowException("Error validating output record: {}\nIn:\n{}"
                                    .format(str(e), json_dumps(ret, indent=4)))
        finally:
            if builder.mutation_manager and readers:
                for r in readers.values():
                    builder.mutation_manager.release_reader(jobname, r)

    def collect_output(self,
                       schema,                # type: Dict[Text, Any]
                       builder,               # type: Builder
                       outdir,                # type: Text
                       fs_access,             # type: StdFsAccess
                       compute_checksum=True  # type: bool
                       ):
        # type: (...) -> Optional[Union[Dict[Text, Any], List[Union[Dict[Text, Any], Text]]]]
        r = []  # type: List[Any]
        empty_and_optional = False
        debug = LOGGER.isEnabledFor(logging.DEBUG)
        if "outputBinding" in schema:
            binding = schema["outputBinding"]
            globpatterns = []  # type: List[Text]

            revmap = partial(command_line_tool.revmap_file, builder, outdir)

            if "glob" in binding:
                with SourceLine(binding, "glob", WorkflowException, debug):
                    for gb in aslist(binding["glob"]):
                        gb = builder.do_eval(gb)
                        if gb:
                            globpatterns.extend(aslist(gb))

                    for gb in globpatterns:
                        if gb.startswith(outdir):
                            gb = gb[len(outdir) + 1:]
                        elif gb == '.':
                            gb = outdir
                        elif gb.startswith('/'):
                            raise WorkflowException("glob patterns must not start with '/'")
                        try:
                            prefix = fs_access.glob(outdir)
                            key = cmp_to_key(cast(Callable[[Text, Text], int], locale.strcoll))
                            r.extend([{"location": g,
                                       "path": fs_access.join(builder.outdir, g[len(prefix[0])+1:]),
                                       "basename": os.path.basename(g),
                                       "nameroot": os.path.splitext(os.path.basename(g))[0],
                                       "nameext": os.path.splitext(os.path.basename(g))[1],
                                       "class": "File" if fs_access.isfile(g) else "Directory"}
                                      for g in sorted(fs_access.glob(fs_access.join(outdir, gb)), key=key)])
                        except (OSError, IOError) as e:
                            LOGGER.warning(Text(e))
                        except Exception:
                            LOGGER.error("Unexpected error from fs_access", exc_info=True)
                            raise

                for files in r:
                    rfile = files.copy()
                    # TODO This function raise an exception and seems to be related to docker (which is not used here)
                    # revmap(rfile)
                    if files["class"] == "Directory":
                        ll = builder.loadListing or (binding and binding.get("loadListing"))
                        if ll and ll != "no_listing":
                            get_listing(fs_access, files, (ll == "deep_listing"))
                    else:
                        with fs_access.open(rfile["location"], 'rb') as f:
                            contents = b""
                            if binding.get("loadContents") or compute_checksum:
                                contents = f.read(CONTENT_LIMIT)
                            if binding.get("loadContents"):
                                files["contents"] = contents.decode("utf-8")
                            if compute_checksum:
                                checksum = hashlib.sha1()
                                while contents != b"":
                                    checksum.update(contents)
                                    contents = f.read(1024 * 1024)
                                files["checksum"] = "sha1$%s" % checksum.hexdigest()
                            f.seek(0, 2)
                            file_size = f.tell()
                        files["size"] = file_size

            optional = False
            single = False
            if isinstance(schema["type"], list):
                if "null" in schema["type"]:
                    optional = True
                if "File" in schema["type"] or "Directory" in schema["type"]:
                    single = True
            elif schema["type"] == "File" or schema["type"] == "Directory":
                single = True

            if "outputEval" in binding:
                with SourceLine(binding, "outputEval", WorkflowException, debug):
                    r = builder.do_eval(binding["outputEval"], context=r)

            if single:
                if not r and not optional:
                    with SourceLine(binding, "glob", WorkflowException, debug):
                        raise WorkflowException("Did not find output file with glob pattern: '{}'".format(globpatterns))
                elif not r and optional:
                    pass
                elif isinstance(r, list):
                    if len(r) > 1:
                        raise WorkflowException("Multiple matches for output item that is a single file.")
                    else:
                        r = r[0]

            if "secondaryFiles" in schema:
                with SourceLine(schema, "secondaryFiles", WorkflowException, debug):
                    for primary in aslist(r):
                        if isinstance(primary, dict):
                            primary.setdefault("secondaryFiles", [])
                            pathprefix = primary["path"][0:primary["path"].rindex('/')+1]
                            for sf in aslist(schema["secondaryFiles"]):
                                if isinstance(sf, dict) or "$(" in sf or "${" in sf:
                                    sfpath = builder.do_eval(sf, context=primary)
                                    subst = False
                                else:
                                    sfpath = sf
                                    subst = True
                                for sfitem in aslist(sfpath):
                                    if isinstance(sfitem, string_types):
                                        if subst:
                                            sfitem = {"path": substitute(primary["path"], sfitem)}
                                        else:
                                            sfitem = {"path": pathprefix+sfitem}
                                    if "path" in sfitem and "location" not in sfitem:
                                        revmap(sfitem)
                                    if fs_access.isfile(sfitem["location"]):
                                        sfitem["class"] = "File"
                                        primary["secondaryFiles"].append(sfitem)
                                    elif fs_access.isdir(sfitem["location"]):
                                        sfitem["class"] = "Directory"
                                        primary["secondaryFiles"].append(sfitem)

            if "format" in schema:
                for primary in aslist(r):
                    primary["format"] = builder.do_eval(schema["format"], context=primary)

            # Ensure files point to local references outside of the run environment
            # TODO: Again removing revmap....
            # adjustFileObjs(r, revmap)

            if not r and optional:
                return None

        if not empty_and_optional and isinstance(schema["type"], dict) and schema["type"]["type"] == "record":
            out = {}
            for f in schema["type"]["fields"]:
                out[shortname(f["name"])] = self.collect_output(  # type: ignore
                    f, builder, outdir, fs_access,
                    compute_checksum=compute_checksum)
            return out
        return r


# noinspection PyPep8Naming
class WpsWorkflowJob(JobBase):
    def __init__(self,
                 builder,           # type: Builder
                 joborder,          # type: Dict[Text, Union[Dict[Text, Any], List, Text, None]]
                 requirements,      # type: List[Dict[Text, Text]]
                 hints,             # type: List[Dict[Text, Text]]
                 name,              # type: Text
                 wps_process,       # type: WpsProcessInterface
                 expected_outputs,  # type: List[ExpectedOutputType]
                 ):                 # type: (...) -> None
        super(WpsWorkflowJob, self).__init__(builder, joborder, None, requirements, hints, name)
        self.wps_process = wps_process
        self.results = None
        self.expected_outputs = {}  # type: ExpectedOutputType
        for output in expected_outputs:
            # TODO Should we support something else?
            if output["type"] == "File":
                # Expecting output to look like this
                # output = {"id": "file:///tmp/random_path/process_name#output_id,
                #           "type": "File",
                #           "outputBinding": {"glob": output_name }
                #          }
                output_id = shortname(output["id"])
                self.expected_outputs[output_id] = output["outputBinding"]["glob"]

    def run(self,
            runtimeContext,     # type: RuntimeContext
            ):                  # type: (...) -> None

        if not os.path.exists(self.tmpdir):
            os.makedirs(self.tmpdir)
        env = self.environment
        vars_to_preserve = runtimeContext.preserve_environment
        if runtimeContext.preserve_entire_environment:
            vars_to_preserve = os.environ
        if vars_to_preserve is not None:
            for key, value in os.environ.items():
                if key in vars_to_preserve and key not in env:
                    # On Windows, subprocess env can't handle unicode.
                    env[key] = str(value) if onWindows() else value
        env["HOME"] = str(self.outdir) if onWindows() else self.outdir
        env["TMPDIR"] = str(self.tmpdir) if onWindows() else self.tmpdir
        if "PATH" not in env:
            env["PATH"] = str(os.environ["PATH"]) if onWindows() else os.environ["PATH"]
        if "SYSTEMROOT" not in env and "SYSTEMROOT" in os.environ:
            env["SYSTEMROOT"] = str(os.environ["SYSTEMROOT"]) if onWindows() else os.environ["SYSTEMROOT"]

        # stageFiles(self.pathmapper, ignoreWritable=True, symLink=True, secret_store=runtimeContext.secret_store)
        if self.generatemapper:
            stageFiles(self.generatemapper, ignoreWritable=self.inplace_update,
                       symLink=True, secret_store=runtimeContext.secret_store)
            relink_initialworkdir(self.generatemapper, self.outdir,
                                  self.builder.outdir, inplace_update=self.inplace_update)

        self.execute([], env, runtimeContext)

    # noinspection PyUnusedLocal
    def execute(self,
                runtime,        # type: List[Text]
                env,            # type: MutableMapping[Text, Text]
                runtimeContext  # type: RuntimeContext
                ):              # type: (...) -> None

        self.results = self.wps_process.execute(self.builder.job, self.outdir, self.expected_outputs)

        if self.joborder and runtimeContext.research_obj:
            job_order = self.joborder
            assert runtimeContext.prov_obj
            assert runtimeContext.process_run_id
            runtimeContext.prov_obj.used_artefacts(
                job_order, runtimeContext.process_run_id, str(self.name))
        outputs = {}  # type: Dict[Text, Text]
        # noinspection PyBroadException
        try:
            rcode = 0

            if self.successCodes:
                process_status = "success"
            elif self.temporaryFailCodes:
                process_status = "temporaryFail"
            elif self.permanentFailCodes:
                process_status = "permanentFail"
            elif rcode == 0:
                process_status = "success"
            else:
                process_status = "permanentFail"

            if self.generatefiles["listing"]:
                assert self.generatemapper is not None
                relink_initialworkdir(
                    self.generatemapper, self.outdir, self.builder.outdir,
                    inplace_update=self.inplace_update)

            outputs = self.collect_outputs(self.outdir)
            outputs = bytes2str_in_dicts(outputs)  # type: ignore
        except OSError as e:
            if e.errno == 2:
                if runtime:
                    LOGGER.error(u"'%s' not found", runtime[0])
                else:
                    LOGGER.error(u"'%s' not found", self.command_line[0])
            else:
                LOGGER.exception("Exception while running job")
            process_status = "permanentFail"
        except WorkflowException as err:
            LOGGER.error(u"[job %s] Job error:\n%s", self.name, err)
            process_status = "permanentFail"
        except Exception:
            LOGGER.exception("Exception while running job")
            process_status = "permanentFail"
        if runtimeContext.research_obj and self.prov_obj and \
                runtimeContext.process_run_id:
            # creating entities for the outputs produced by each step (in the provenance document)
            self.prov_obj.generate_output_prov(
                outputs, runtimeContext.process_run_id, str(self.name))
            self.prov_obj.document.wasEndedBy(
                runtimeContext.process_run_id, None, self.prov_obj.workflow_run_uri,
                now())
        if process_status != "success":
            LOGGER.warning(u"[job %s] completed %s", self.name, process_status)
        else:
            LOGGER.info(u"[job %s] completed %s", self.name, process_status)

        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(u"[job %s] %s", self.name, json_dumps(outputs, indent=4))

        if self.generatemapper and runtimeContext.secret_store:
            # Delete any runtime-generated files containing secrets.
            for f, p in self.generatemapper.items():
                if p.type == "CreateFile":
                    if runtimeContext.secret_store.has_secret(p.resolved):
                        host_outdir = self.outdir
                        container_outdir = self.builder.outdir
                        host_outdir_tgt = p.target
                        if p.target.startswith(container_outdir + '/'):
                            host_outdir_tgt = os.path.join(
                                host_outdir, p.target[len(container_outdir)+1:])
                        os.remove(host_outdir_tgt)

        if runtimeContext.workflow_eval_lock is None:
            raise WorkflowException("runtimeContext.workflow_eval_lock must not be None")

        with runtimeContext.workflow_eval_lock:
            self.output_callback(outputs, process_status)

        if self.stagedir and os.path.exists(self.stagedir):
            LOGGER.debug(u"[job %s] Removing input staging directory %s", self.name, self.stagedir)
            shutil.rmtree(self.stagedir, True)

        if runtimeContext.rm_tmpdir:
            LOGGER.debug(u"[job %s] Removing temporary directory %s", self.name, self.tmpdir)
            shutil.rmtree(self.tmpdir, True)