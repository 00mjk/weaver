"""
This module should contain any and every definitions in use to build the swagger UI,
so that one can update the swagger without touching any other files after the initial integration
"""
# pylint: disable=C0103,invalid-name

from colander import (
    Boolean,
    DateTime,
    Float,
    Integer,
    MappingSchema as MapSchema,
    OneOf,
    Range,
    SequenceSchema as SeqSchema,
    String,
    drop
)
from cornice import Service

from weaver import __meta__
from weaver.config import WEAVER_CONFIGURATION_EMS
from weaver.execute import (
    EXECUTE_CONTROL_OPTION_ASYNC,
    EXECUTE_CONTROL_OPTIONS,
    EXECUTE_MODE_ASYNC,
    EXECUTE_MODE_AUTO,
    EXECUTE_MODE_OPTIONS,
    EXECUTE_RESPONSE_OPTIONS,
    EXECUTE_RESPONSE_RAW,
    EXECUTE_TRANSMISSION_MODE_OPTIONS,
    EXECUTE_TRANSMISSION_MODE_REFERENCE
)
from weaver.formats import (
    ACCEPT_LANGUAGE_EN_CA,
    ACCEPT_LANGUAGES,
    CONTENT_TYPE_APP_JSON,
    CONTENT_TYPE_APP_XML,
    CONTENT_TYPE_TEXT_HTML,
    CONTENT_TYPE_TEXT_PLAIN
)
from weaver.owsexceptions import OWSMissingParameterValue
from weaver.sort import JOB_SORT_VALUES, QUOTE_SORT_VALUES, SORT_CREATED, SORT_ID, SORT_PROCESS
from weaver.status import JOB_STATUS_CATEGORIES, STATUS_ACCEPTED, STATUS_COMPLIANT_OGC
from weaver.visibility import VISIBILITY_PUBLIC, VISIBILITY_VALUES
from weaver.wps_restapi.colander_extras import (
    ExtendedMappingSchema,
    ExtendedSequenceSchema,
    ExtendedSchemaNode,
    OneOfKeywordSchema,
    VariableMappingSchema
)
from weaver.wps_restapi.utils import wps_restapi_base_path


API_TITLE = "Weaver REST API"
API_INFO = {
    "description": __meta__.__description__,
    "contact": {"name": __meta__.__authors__, "email": __meta__.__emails__, "url": __meta__.__source_repository__}
}
API_DOCS = {
    "description": "{} documentation".format(__meta__.__title__),
    "url": __meta__.__documentation_url__
}

CWL_DOC_MESSAGE = "Note that multiple formats are supported and not all specification variants or parameters " \
                  "are presented here. Please refer to official CWL documentation for more details " \
                  "(https://www.commonwl.org/)."

#########################################################
# API tags
#########################################################

TAG_API = "API"
TAG_JOBS = "Jobs"
TAG_VISIBILITY = "Visibility"
TAG_BILL_QUOTE = "Billing & Quoting"
TAG_PROVIDER_PROCESS = "Provider Processes"
TAG_PROVIDERS = "Providers"
TAG_PROCESSES = "Processes"
TAG_GETCAPABILITIES = "GetCapabilities"
TAG_DESCRIBEPROCESS = "DescribeProcess"
TAG_EXECUTE = "Execute"
TAG_DISMISS = "Dismiss"
TAG_STATUS = "Status"
TAG_DEPLOY = "Deploy"
TAG_RESULTS = "Results"
TAG_EXCEPTIONS = "Exceptions"
TAG_LOGS = "Logs"

#########################################################################
# API endpoints
# These "services" are wrappers that allow Cornice to generate the JSON API
###############################################################################

api_frontpage_service = Service(name="api_frontpage", path="/")
api_swagger_ui_service = Service(name="api_swagger_ui", path="/api")
api_swagger_json_service = Service(name="api_swagger_json", path="/json")
api_versions_service = Service(name="api_versions", path="/versions")
api_conformance_service = Service(name="api_conformance", path="/conformance")

quotes_service = Service(name="quotes", path="/quotations")
quote_service = Service(name="quote", path=quotes_service.path + "/{quote_id}")
bills_service = Service(name="bills", path="/bills")
bill_service = Service(name="bill", path=bills_service.path + "/{bill_id}")

jobs_service = Service(name="jobs", path="/jobs")
job_service = Service(name="job", path=jobs_service.path + "/{job_id}")
job_results_service = Service(name="job_results", path=job_service.path + "/results")
job_exceptions_service = Service(name="job_exceptions", path=job_service.path + "/exceptions")
job_outputs_service = Service(name="job_outputs", path=job_service.path + "/outputs")
job_inputs_service = Service(name="job_inputs", path=job_service.path + "/inputs")
job_logs_service = Service(name="job_logs", path=job_service.path + "/logs")

processes_service = Service(name="processes", path="/processes")
process_service = Service(name="process", path=processes_service.path + "/{process_id}")
process_quotes_service = Service(name="process_quotes", path=process_service.path + quotes_service.path)
process_quote_service = Service(name="process_quote", path=process_service.path + quote_service.path)
process_visibility_service = Service(name="process_visibility", path=process_service.path + "/visibility")
process_package_service = Service(name="process_package", path=process_service.path + "/package")
process_payload_service = Service(name="process_payload", path=process_service.path + "/payload")
process_jobs_service = Service(name="process_jobs", path=process_service.path + jobs_service.path)
process_job_service = Service(name="process_job", path=process_service.path + job_service.path)
process_results_service = Service(name="process_results", path=process_service.path + job_results_service.path)
process_inputs_service = Service(name="process_inputs", path=process_service.path + job_inputs_service.path)
process_outputs_service = Service(name="process_outputs", path=process_service.path + job_outputs_service.path)
process_exceptions_service = Service(name="process_exceptions", path=process_service.path + job_exceptions_service.path)
process_logs_service = Service(name="process_logs", path=process_service.path + job_logs_service.path)

providers_service = Service(name="providers", path="/providers")
provider_service = Service(name="provider", path=providers_service.path + "/{provider_id}")
provider_processes_service = Service(name="provider_processes", path=provider_service.path + processes_service.path)
provider_process_service = Service(name="provider_process", path=provider_service.path + process_service.path)
provider_jobs_service = Service(name="provider_jobs", path=provider_service.path + process_jobs_service.path)
provider_job_service = Service(name="provider_job", path=provider_service.path + process_job_service.path)
provider_results_service = Service(name="provider_results", path=provider_service.path + process_results_service.path)
provider_inputs_service = Service(name="provider_inputs", path=provider_service.path + process_inputs_service.path)
provider_outputs_service = Service(name="provider_outputs", path=provider_service.path + process_outputs_service.path)
provider_logs_service = Service(name="provider_logs", path=provider_service.path + process_logs_service.path)
provider_exceptions_service = Service(name="provider_exceptions",
                                      path=provider_service.path + process_exceptions_service.path)

#########################################################
# Generic schemas
#########################################################


class SLUG(ExtendedSchemaNode):
    schema_type = String
    description = "Slug name pattern."
    example = "some-object-slug-name"
    pattern = "^[a-z0-9]+(?:-[a-z0-9]+)*$"


class URL(ExtendedSchemaNode):
    schema_type = String
    description = "URL reference"
    format = "url"


class UUID(ExtendedSchemaNode):
    schema_type = String
    description = "UUID"
    example = "a9d14bf4-84e0-449a-bac8-16e598efe807"
    format = "uuid"


class Version(ExtendedSchemaNode):
    # note: internally use LooseVersion, so don't be too strict about pattern
    schema_type = String
    description = "Version string."
    example = "1.2.3"
    format = "version"
    pattern = r"^(\d+\.)(\d+\.)(\d+\.)(\d).*$"


class JsonHeader(ExtendedMappingSchema):
    content_type = ExtendedSchemaNode(String(), example=CONTENT_TYPE_APP_JSON, default=CONTENT_TYPE_APP_JSON)
    content_type.name = "Content-Type"


class HtmlHeader(ExtendedMappingSchema):
    content_type = ExtendedSchemaNode(String(), example=CONTENT_TYPE_TEXT_HTML, default=CONTENT_TYPE_TEXT_HTML)
    content_type.name = "Content-Type"


class XmlHeader(ExtendedMappingSchema):
    content_type = ExtendedSchemaNode(String(), example=CONTENT_TYPE_APP_XML, default=CONTENT_TYPE_APP_XML)
    content_type.name = "Content-Type"


class AcceptHeader(ExtendedMappingSchema):
    Accept = ExtendedSchemaNode(String(), missing=drop, default=CONTENT_TYPE_APP_JSON, validator=OneOf([
        CONTENT_TYPE_APP_JSON,
        CONTENT_TYPE_APP_XML,
        # CONTENT_TYPE_TEXT_HTML,   # defaults to JSON for easy use within browsers
    ]))


class AcceptLanguageHeader(ExtendedMappingSchema):
    AcceptLanguage = ExtendedSchemaNode(String(), missing=drop)
    AcceptLanguage.name = "Accept-Language"


class Headers(AcceptHeader, AcceptLanguageHeader):
    """Headers that can indicate how to adjust the behavior and/or result the be provided in the response."""


class KeywordList(ExtendedSequenceSchema):
    keyword = ExtendedSchemaNode(String())


class Language(ExtendedSchemaNode):
    schema_type = String
    example = ACCEPT_LANGUAGE_EN_CA
    validator = OneOf(ACCEPT_LANGUAGES)


class ValueLanguage(ExtendedMappingSchema):
    value = ExtendedSchemaNode(String())
    lang = Language(missing=drop)


class LinkLanguage(ExtendedMappingSchema):
    href = URL()
    hreflang = Language(missing=drop)


class LinkMeta(ExtendedMappingSchema):
    rel = ExtendedSchemaNode(String())
    type = ExtendedSchemaNode(String(), missing=drop)
    title = ExtendedSchemaNode(String(), missing=drop)


class Link(LinkLanguage, LinkMeta):
    pass


class MetadataContent(OneOfKeywordSchema, LinkMeta):
    _one_of = [
        LinkLanguage(),
        ValueLanguage()
    ]


class Metadata(MetadataContent):
    role = URL(missing=drop)


class MetadataList(ExtendedSequenceSchema):
    item = Metadata()


class LinkList(ExtendedSequenceSchema):
    link = Link()


class LandingPage(ExtendedMappingSchema):
    links = LinkList()


class Format(ExtendedMappingSchema):
    mimeType = ExtendedSchemaNode(String(), missing=drop)
    schema = ExtendedSchemaNode(String(), missing=drop)
    encoding = ExtendedSchemaNode(String(), missing=drop)


class FormatDefault(Format):
    """Format for process input are assumed plain text if the MIME-type was omitted and is not
    one of the known formats by this instance. When executing a job, the best match will be used
    to run the process, and will fallback to the default as last resort.
    """
    mimeType = ExtendedSchemaNode(String(), default=CONTENT_TYPE_TEXT_PLAIN, example=CONTENT_TYPE_APP_JSON)


class FormatDescription(FormatDefault):
    maximumMegabytes = ExtendedSchemaNode(Integer(), missing=drop)
    default = ExtendedSchemaNode(Boolean(), missing=drop, default=False,
                         description="Indicate if this format should be considered as the default one in case none"
                                     "of the other allowed/supported formats is matched against the job input.")


class FormatDescriptionList(ExtendedSequenceSchema):
    format = FormatDescription()


class AdditionalParameterValuesList(ExtendedSequenceSchema):
    values = ExtendedSchemaNode(String())


class AdditionalParameter(ExtendedMappingSchema):
    name = ExtendedSchemaNode(String())
    values = AdditionalParameterValuesList()


class AdditionalParameterList(ExtendedSequenceSchema):
    item = AdditionalParameter()


class AdditionalParameters(ExtendedMappingSchema):
    role = ExtendedSchemaNode(String(), missing=drop)
    parameters = AdditionalParameterList(missing=drop)


class AdditionalParametersList(ExtendedSequenceSchema):
    additionalParameter = AdditionalParameters()


class Content(ExtendedMappingSchema):
    href = ExtendedSchemaNode(String(), format=URL, description="URL to CWL file.", title="href",
                              example="http://some.host/applications/cwl/multisensor_ndvi.cwl")


class Offering(ExtendedMappingSchema):
    code = ExtendedSchemaNode(String(), missing=drop, description="Descriptor of represented information in 'content'.")
    content = Content(title="content", missing=drop)


class OWSContext(ExtendedMappingSchema):
    offering = Offering(title="offering")


class DescriptionType(ExtendedMappingSchema):
    id = ExtendedSchemaNode(String())
    title = ExtendedSchemaNode(String(), missing=drop)
    abstract = ExtendedSchemaNode(String(), missing=drop)
    keywords = KeywordList(missing=drop)
    owsContext = OWSContext(missing=drop, title="owsContext")
    metadata = MetadataList(missing=drop)
    additionalParameters = AdditionalParametersList(missing=drop, title="additionalParameters")
    links = LinkList(missing=drop, title="links")


class AnyOccursType(OneOfKeywordSchema):
    _one_of = [
        ExtendedSchemaNode(Integer()),
        ExtendedSchemaNode(String())
    ]


class WithMinMaxOccurs(ExtendedMappingSchema):
    minOccurs = AnyOccursType(title="minOccurs", missing=drop,
                              description="Minimum allowed number of data occurrences of this item.")
    maxOccurs = AnyOccursType(title="maxOccurs", missing=drop,
                              description="Maximum allowed number of data occurrences of this item.")


class ComplexInputType(DescriptionType, WithMinMaxOccurs):
    formats = FormatDescriptionList()


class SupportedCrs(ExtendedMappingSchema):
    crs = ExtendedSchemaNode(String(), format=URL)
    default = ExtendedSchemaNode(Boolean(), missing=drop)


class SupportedCrsList(ExtendedSequenceSchema):
    item = SupportedCrs()


class BoundingBoxInputType(DescriptionType, WithMinMaxOccurs):
    supportedCRS = SupportedCrsList()


class LiteralReference(ExtendedMappingSchema):
    reference = URL()


class DataTypeSchema(ExtendedMappingSchema):
    name = ExtendedSchemaNode(String())
    reference = URL(missing=drop)


class UomSchema(DataTypeSchema):
    pass


class AllowedValuesList(ExtendedSequenceSchema):
    allowedValues = ExtendedSchemaNode(String())


class AllowedValues(ExtendedMappingSchema):
    allowedValues = AllowedValuesList()


class AllowedRange(ExtendedMappingSchema):
    minimumValue = ExtendedSchemaNode(String(), missing=drop)
    maximumValue = ExtendedSchemaNode(String(), missing=drop)
    spacing = ExtendedSchemaNode(String(), missing=drop)
    rangeClosure = ExtendedSchemaNode(String(), missing=drop,
                                      validator=OneOf(["closed", "open", "open-closed", "closed-open"]))


class AllowedRangesList(ExtendedSequenceSchema):
    allowedRanges = AllowedRange()


class AllowedRanges(ExtendedMappingSchema):
    allowedRanges = AllowedRangesList()


class AnyValue(ExtendedMappingSchema):
    anyValue = ExtendedSchemaNode(Boolean(), missing=drop, default=True)


class ValuesReference(ExtendedMappingSchema):
    valueReference = ExtendedSchemaNode(String(), format=URL, )


class LiteralDataDomainType(OneOfKeywordSchema):
    _one_of = (AllowedValues,
               AllowedRanges,
               ValuesReference,
               AnyValue)  # must be last because it"s the most permissive
    defaultValue = ExtendedSchemaNode(String(), missing=drop)
    dataType = DataTypeSchema(missing=drop)
    uom = UomSchema(missing=drop)


class LiteralDataDomainTypeList(ExtendedSequenceSchema):
    literalDataDomain = LiteralDataDomainType()


class LiteralInputType(DescriptionType, WithMinMaxOccurs):
    literalDataDomains = LiteralDataDomainTypeList(missing=drop)


class InputType(OneOfKeywordSchema):
    _one_of = (
        BoundingBoxInputType,
        ComplexInputType,  # should be 2nd to last because very permission, but requires format at least
        LiteralInputType,  # must be last because it"s the most permissive (all can default if omitted)
    )


class InputTypeList(ExtendedSequenceSchema):
    input = InputType()


class LiteralOutputType(ExtendedMappingSchema):
    literalDataDomains = LiteralDataDomainTypeList(missing=drop)


class BoundingBoxOutputType(ExtendedMappingSchema):
    supportedCRS = SupportedCrsList()


class ComplexOutputType(ExtendedMappingSchema):
    formats = FormatDescriptionList()


class OutputDataDescriptionType(DescriptionType):
    pass


class OutputType(OneOfKeywordSchema, OutputDataDescriptionType):
    _one_of = (
        BoundingBoxOutputType,
        ComplexOutputType,  # should be 2nd to last because very permission, but requires format at least
        LiteralOutputType,  # must be last because it"s the most permissive (all can default if omitted)
    )


class OutputDescriptionList(ExtendedSequenceSchema):
    item = OutputType()


class JobExecuteModeEnum(ExtendedSchemaNode):
    schema_type = String

    def __init__(self, *args, **kwargs):    # noqa: E811
        kwargs.pop("validator", None)   # ignore passed argument and enforce the validator
        super(JobExecuteModeEnum, self).__init__(
            self.schema_type(),
            title=kwargs.get("title", "mode"),
            default=kwargs.get("default", EXECUTE_MODE_AUTO),
            example=kwargs.get("example", EXECUTE_MODE_ASYNC),
            validator=OneOf(list(EXECUTE_MODE_OPTIONS)),
            **kwargs)


class JobControlOptionsEnum(ExtendedSchemaNode):
    schema_type = String

    def __init__(self, *args, **kwargs):    # noqa: E811
        kwargs.pop("validator", None)   # ignore passed argument and enforce the validator
        super(JobControlOptionsEnum, self).__init__(
            self.schema_type(),
            title="jobControlOptions",
            default=kwargs.get("default", EXECUTE_CONTROL_OPTION_ASYNC),
            example=kwargs.get("example", EXECUTE_CONTROL_OPTION_ASYNC),
            validator=OneOf(list(EXECUTE_CONTROL_OPTIONS)),
            **kwargs)


class JobResponseOptionsEnum(ExtendedSchemaNode):
    schema_type = String

    def __init__(self, *args, **kwargs):    # noqa: E811
        kwargs.pop("validator", None)   # ignore passed argument and enforce the validator
        super(JobResponseOptionsEnum, self).__init__(
            self.schema_type(),
            title=kwargs.get("title", "response"),
            default=kwargs.get("default", EXECUTE_RESPONSE_RAW),
            example=kwargs.get("example", EXECUTE_RESPONSE_RAW),
            validator=OneOf(list(EXECUTE_RESPONSE_OPTIONS)),
            **kwargs)


class TransmissionModeEnum(ExtendedSchemaNode):
    schema_type = String

    def __init__(self, *args, **kwargs):    # noqa: E811
        kwargs.pop("validator", None)   # ignore passed argument and enforce the validator
        super(TransmissionModeEnum, self).__init__(
            self.schema_type(),
            title=kwargs.get("title", "transmissionMode"),
            default=kwargs.get("default", EXECUTE_TRANSMISSION_MODE_REFERENCE),
            example=kwargs.get("example", EXECUTE_TRANSMISSION_MODE_REFERENCE),
            validator=OneOf(list(EXECUTE_TRANSMISSION_MODE_OPTIONS)),
            **kwargs)


class JobStatusEnum(ExtendedSchemaNode):
    schema_type = String

    def __init__(self, *args, **kwargs):    # noqa: E811
        kwargs.pop("validator", None)   # ignore passed argument and enforce the validator
        super(JobStatusEnum, self).__init__(
            self.schema_type(),
            default=kwargs.get("default", None),
            example=kwargs.get("example", STATUS_ACCEPTED),
            validator=OneOf(list(JOB_STATUS_CATEGORIES[STATUS_COMPLIANT_OGC])),
            **kwargs)


class JobSortEnum(ExtendedSchemaNode):
    schema_type = String

    def __init__(self, *args, **kwargs):    # noqa: E811
        kwargs.pop("validator", None)   # ignore passed argument and enforce the validator
        super(JobSortEnum, self).__init__(
            String(),
            default=kwargs.get("default", SORT_CREATED),
            example=kwargs.get("example", SORT_CREATED),
            validator=OneOf(list(JOB_SORT_VALUES)),
            **kwargs)


class QuoteSortEnum(ExtendedSchemaNode):
    schema_type = String

    def __init__(self, *args, **kwargs):  # noqa: E811
        kwargs.pop("validator", None)  # ignore passed argument and enforce the validator
        super(QuoteSortEnum, self).__init__(
            self.schema_type(),
            default=kwargs.get("default", SORT_ID),
            example=kwargs.get("example", SORT_PROCESS),
            validator=OneOf(list(QUOTE_SORT_VALUES)),
            **kwargs)


class LaunchJobQuerystring(ExtendedMappingSchema):
    field_string = ExtendedSchemaNode(String(), default=None, missing=drop,
                              description="Comma separated tags that can be used to filter jobs later")
    field_string.name = "tags"


class Visibility(ExtendedMappingSchema):
    value = ExtendedSchemaNode(String(), validator=OneOf(list(VISIBILITY_VALUES)), example=VISIBILITY_PUBLIC)


#########################################################
# Path parameter definitions
#########################################################

class AnyId(OneOfKeywordSchema):
    _one_of = (
        SLUG(description="Generic identifier. This is a user-friendly slug-name. "
                         "Note that this will represent the latest process matching this name. "
                         "For specific process version, use the UUID instead."),
        UUID(description="Unique identifier.")
    )


class ProcessPath(ExtendedMappingSchema):
    process_id = ExtendedSchemaNode(String(), description="The process identifier.")
    # NOTE: future (https://github.com/crim-ca/weaver/issues/107)
    #   process_id = AnyId(description="The process identifier.")


class ProviderPath(ExtendedMappingSchema):
    provider_id = ExtendedSchemaNode(String(), description="The provider identifier")
    # NOTE: future (https://github.com/crim-ca/weaver/issues/107)
    #   provider_id = AnyId(description="The process identifier.")


class JobPath(ExtendedMappingSchema):
    job_id = UUID(description="The job id")


class BillPath(ExtendedMappingSchema):
    bill_id = UUID(description="The bill id")


class QuotePath(ExtendedMappingSchema):
    quote_id = UUID(description="The quote id")


class ResultPath(ExtendedMappingSchema):
    result_id = UUID(description="The result id")


#########################################################
# These classes define each of the endpoints parameters
#########################################################


class FrontpageEndpoint(ExtendedMappingSchema):
    header = Headers()


class VersionsEndpoint(ExtendedMappingSchema):
    header = Headers()


class ConformanceEndpoint(ExtendedMappingSchema):
    header = Headers()


class SwaggerJSONEndpoint(ExtendedMappingSchema):
    header = Headers()


class SwaggerUIEndpoint(ExtendedMappingSchema):
    pass


class ProviderEndpoint(ProviderPath):
    header = Headers()


class ProviderProcessEndpoint(ProviderPath, ProcessPath):
    header = Headers()


class ProcessEndpoint(ProcessPath):
    header = Headers()


class ProcessPackageEndpoint(ProcessPath):
    header = Headers()


class ProcessPayloadEndpoint(ProcessPath):
    header = Headers()


class ProcessVisibilityGetEndpoint(ProcessPath):
    header = Headers()


class ProcessVisibilityPutEndpoint(ProcessPath):
    header = Headers()
    body = Visibility()


class FullJobEndpoint(ProviderPath, ProcessPath, JobPath):
    header = Headers()


class ShortJobEndpoint(JobPath):
    header = Headers()


class ProcessInputsEndpoint(ProcessPath, JobPath):
    header = Headers()


class ProviderInputsEndpoint(ProviderPath, ProcessPath, JobPath):
    header = Headers()


class JobInputsEndpoint(JobPath):
    header = Headers()


class ProcessOutputsEndpoint(ProcessPath, JobPath):
    header = Headers()


class ProviderOutputsEndpoint(ProviderPath, ProcessPath, JobPath):
    header = Headers()


class JobOutputsEndpoint(JobPath):
    header = Headers()


class ProcessResultsEndpoint(ProcessPath, JobPath):
    header = Headers()


class FullResultsEndpoint(ProviderPath, ProcessPath, JobPath):
    header = Headers()


class ShortResultsEndpoint(ProviderPath, ProcessPath, JobPath):
    header = Headers()


class FullExceptionsEndpoint(ProviderPath, ProcessPath, JobPath):
    header = Headers()


class ShortExceptionsEndpoint(JobPath):
    header = Headers()


class ProcessExceptionsEndpoint(ProcessPath, JobPath):
    header = Headers()


class FullLogsEndpoint(ProviderPath, ProcessPath, JobPath):
    header = Headers()


class ShortLogsEndpoint(JobPath):
    header = Headers()


class ProcessLogsEndpoint(ProcessPath, JobPath):
    header = Headers()


##################################################################
# These classes define schemas for requests that feature a body
##################################################################


class CreateProviderRequestBody(ExtendedMappingSchema):
    id = ExtendedSchemaNode(String())
    url = URL(description="Endpoint where to query the provider.")
    public = ExtendedSchemaNode(Boolean())


class InputDataType(ExtendedMappingSchema):
    id = ExtendedSchemaNode(String())


class OutputDataType(ExtendedMappingSchema):
    id = ExtendedSchemaNode(String())
    format = Format(missing=drop)


class Output(OutputDataType):
    transmissionMode = TransmissionModeEnum(missing=drop)


class OutputList(ExtendedSequenceSchema):
    output = Output()


class ProviderSummarySchema(ExtendedMappingSchema):
    """WPS provider summary definition."""
    id = ExtendedSchemaNode(String())
    url = URL(description="Endpoint of the provider.")
    title = ExtendedSchemaNode(String())
    abstract = ExtendedSchemaNode(String())
    public = ExtendedSchemaNode(Boolean())


class ProviderCapabilitiesSchema(ExtendedMappingSchema):
    """WPS provider capabilities."""
    id = ExtendedSchemaNode(String())
    url = URL(description="WPS GetCapabilities URL of the provider.")
    title = ExtendedSchemaNode(String())
    abstract = ExtendedSchemaNode(String())
    contact = ExtendedSchemaNode(String())
    type = ExtendedSchemaNode(String())


class TransmissionModeList(ExtendedSequenceSchema):
    item = TransmissionModeEnum(missing=drop)


class JobControlOptionsList(ExtendedSequenceSchema):
    item = JobControlOptionsEnum(missing=drop)


class ExceptionReportType(ExtendedMappingSchema):
    code = ExtendedSchemaNode(String())
    description = ExtendedSchemaNode(String(), missing=drop)


class ProcessSummary(DescriptionType):
    """WPS process definition."""
    version = ExtendedSchemaNode(String(), missing=drop)
    jobControlOptions = JobControlOptionsList(missing=drop)
    outputTransmission = TransmissionModeList(missing=drop)
    processDescriptionURL = URL(description="Process description endpoint.", missing=drop)


class ProcessSummaryList(ExtendedSequenceSchema):
    item = ProcessSummary()


class ProcessCollection(ExtendedMappingSchema):
    processes = ProcessSummaryList()


class Process(DescriptionType):
    inputs = InputTypeList(missing=drop)
    outputs = OutputDescriptionList(missing=drop)
    executeEndpoint = URL(description="Endpoint where the process can be executed from.", missing=drop)


class ProcessOutputDescriptionSchema(ExtendedMappingSchema):
    """WPS process output definition."""
    dataType = ExtendedSchemaNode(String())
    defaultValue = ExtendedMappingSchema()
    id = ExtendedSchemaNode(String())
    abstract = ExtendedSchemaNode(String())
    title = ExtendedSchemaNode(String())


class JobStatusInfo(ExtendedMappingSchema):
    jobId = UUID(example="a9d14bf4-84e0-449a-bac8-16e598efe807", description="ID of the job.")
    status = JobStatusEnum()
    message = ExtendedSchemaNode(String(), missing=drop)
    expirationDate = ExtendedSchemaNode(DateTime(), missing=drop)
    estimatedCompletion = ExtendedSchemaNode(DateTime(), missing=drop)
    duration = ExtendedSchemaNode(String(), missing=drop, description="Duration of the process execution.")
    nextPoll = ExtendedSchemaNode(DateTime(), missing=drop)
    percentCompleted = ExtendedSchemaNode(Integer(), example=0, validator=Range(min=0, max=100))
    links = LinkList(missing=drop)


class JobEntrySchema(OneOfKeywordSchema):
    _one_of = (
        JobStatusInfo,
        ExtendedSchemaNode(String(), description="Job ID."),
    )
    # note:
    #   Since JobId is a simple string (not a dict), no additional mapping field can be added here.
    #   They will be discarded by `OneOfKeywordSchema.deserialize()`.


class JobCollection(ExtendedSequenceSchema):
    item = JobEntrySchema()


class CreatedJobStatusSchema(ExtendedMappingSchema):
    status = ExtendedSchemaNode(String(), example=STATUS_ACCEPTED)
    location = ExtendedSchemaNode(String(), example="http://{host}/weaver/processes/{my-process-id}/jobs/{my-job-id}")
    jobID = UUID(description="ID of the created job.")


class CreatedQuotedJobStatusSchema(CreatedJobStatusSchema):
    bill = UUID(description="ID of the created bill.")


class GetPagingJobsSchema(ExtendedMappingSchema):
    jobs = JobCollection()
    limit = ExtendedSchemaNode(Integer())
    page = ExtendedSchemaNode(Integer())


class GroupedJobsCategorySchema(ExtendedMappingSchema):
    category = VariableMappingSchema(description="Grouping values that compose the corresponding job list category.")
    jobs = JobCollection(description="List of jobs that matched the corresponding grouping values.")
    count = ExtendedSchemaNode(Integer(), description="Number of matching jobs for the corresponding group category.")


class GroupedCategoryJobsSchema(ExtendedSequenceSchema):
    job_group_category_item = GroupedJobsCategorySchema()


class GetGroupedJobsSchema(ExtendedMappingSchema):
    groups = GroupedCategoryJobsSchema()


class GetQueriedJobsSchema(OneOfKeywordSchema):
    _one_of = (
        GetPagingJobsSchema,
        GetGroupedJobsSchema,
    )
    total = ExtendedSchemaNode(Integer(),
                               description="Total number of matched jobs regardless of grouping or paging result.")


class DismissedJobSchema(ExtendedMappingSchema):
    status = JobStatusEnum()
    jobID = UUID(description="ID of the job.")
    message = ExtendedSchemaNode(String(), example="Job dismissed.")
    percentCompleted = ExtendedSchemaNode(Integer(), example=0)


class QuoteProcessParametersSchema(ExtendedMappingSchema):
    inputs = InputTypeList(missing=drop)
    outputs = OutputDescriptionList(missing=drop)
    mode = JobExecuteModeEnum(missing=drop)
    response = JobResponseOptionsEnum(missing=drop)


class AlternateQuotation(ExtendedMappingSchema):
    id = UUID(description="Quote ID.")
    title = ExtendedSchemaNode(String(), description="Name of the quotation.", missing=drop)
    description = ExtendedSchemaNode(String(), description="Description of the quotation.", missing=drop)
    price = ExtendedSchemaNode(Float(), description="Process execution price.")
    currency = ExtendedSchemaNode(String(), description="Currency code in ISO-4217 format.")
    expire = ExtendedSchemaNode(DateTime(), description="Expiration date and time of the quote in ISO-8601 format.")
    created = ExtendedSchemaNode(DateTime(), description="Creation date and time of the quote in ISO-8601 format.")
    details = ExtendedSchemaNode(String(), description="Details of the quotation.", missing=drop)
    estimatedTime = ExtendedSchemaNode(String(), description="Estimated process execution duration.", missing=drop)


class AlternateQuotationList(ExtendedSequenceSchema):
    step = AlternateQuotation(description="Quote of a workflow step process.")


# same as base Format, but for process/job responses instead of process submission
# (ie: 'Format' is for allowed/supported formats, this is the result format)
class DataEncodingAttributes(Format):
    pass


class Reference(DataEncodingAttributes):
    href = URL(description="Endpoint of the reference.")
    body = ExtendedSchemaNode(String(), missing=drop)
    bodyReference = URL(missing=drop)


class DataTypeFormats(OneOfKeywordSchema):
    """Items with 'data' key, only literal data.

    .. note::
        :class:`URL` is not here contrary to :class:`ValueTypeFormats`.

    .. seealso::
        - :class:`DataType`
        - :class:`AnyType`
    """
    _one_of = (
        ExtendedSchemaNode(Float()),  # before Integer because more restrictive Number format
        ExtendedSchemaNode(Integer()),  # before Boolean because bool can be interpreted using int
        ExtendedSchemaNode(Boolean()),
        ExtendedSchemaNode(String())
    )


class DataType(DataEncodingAttributes):
    data = DataTypeFormats(description="Value provided by one of the accepted types.")


class ValueTypeFormats(OneOfKeywordSchema):
    """OGC-specific format, always 'value' key regardless of content.

    .. seealso::
        - :class:`ValueType`
        - :class:`AnyType`
    """
    _one_of = (
        ExtendedSchemaNode(Float()),  # before Integer because more restrictive Number format
        ExtendedSchemaNode(Integer()),  # before Boolean because bool can be interpreted using int
        ExtendedSchemaNode(Boolean()),
        URL(), # before String because more restrictive (format)
        ExtendedSchemaNode(String())
    )


class ValueType(ExtendedMappingSchema):
    value = ValueTypeFormats(description="Value provided by one of the accepted types.")


class AnyType(OneOfKeywordSchema):
    """Permissive variants that we attempt to parse automatically."""
    _one_of = (
        # literal data with 'data' key
        DataType,
        # same with 'value' key (OGC specification)
        ValueType,
        # HTTP references with various keywords
        LiteralReference, Reference
    )


class Input(InputDataType, AnyType):
    """
    Default value to be looked for uses key 'value' to conform to OGC API standard.
    We still look for 'href', 'data' and 'reference' to remain back-compatible.
    """


class InputList(ExtendedSequenceSchema):
    item = Input(missing=drop, description="Received input definition during job submission.")


class Execute(ExtendedMappingSchema):
    inputs = InputList(missing=drop)
    outputs = OutputList()
    mode = ExtendedSchemaNode(String(), validator=OneOf(list(EXECUTE_MODE_OPTIONS)))
    notification_email = ExtendedSchemaNode(
        String(),
        missing=drop,
        description="Optionally send a notification email when the job is done.")
    response = ExtendedSchemaNode(String(), validator=OneOf(list(EXECUTE_RESPONSE_OPTIONS)))


class Quotation(ExtendedMappingSchema):
    id = UUID(description="Quote ID.")
    title = ExtendedSchemaNode(String(), description="Name of the quotation.", missing=drop)
    description = ExtendedSchemaNode(String(), description="Description of the quotation.", missing=drop)
    processId = UUID(description="Corresponding process ID.")
    price = ExtendedSchemaNode(Float(), description="Process execution price.")
    currency = ExtendedSchemaNode(String(), description="Currency code in ISO-4217 format.")
    expire = ExtendedSchemaNode(DateTime(), description="Expiration date and time of the quote in ISO-8601 format.")
    created = ExtendedSchemaNode(DateTime(), description="Creation date and time of the quote in ISO-8601 format.")
    userId = UUID(description="User id that requested the quote.")
    details = ExtendedSchemaNode(String(), description="Details of the quotation.", missing=drop)
    estimatedTime = ExtendedSchemaNode(DateTime(), missing=drop,
                                       description="Estimated duration of the process execution.")
    processParameters = Execute(title="ProcessExecuteParameters")
    alternativeQuotations = AlternateQuotationList(missing=drop)


class QuoteProcessListSchema(ExtendedSequenceSchema):
    step = Quotation(description="Quote of a workflow step process.")


class QuoteSchema(ExtendedMappingSchema):
    id = UUID(description="Quote ID.")
    process = ExtendedSchemaNode(String(), description="Corresponding process ID.")
    steps = QuoteProcessListSchema(description="Child processes and prices.")
    total = ExtendedSchemaNode(Float(), description="Total of the quote including step processes.")


class QuotationList(ExtendedSequenceSchema):
    item = ExtendedSchemaNode(String(), description="Bill ID.")


class QuotationListSchema(ExtendedMappingSchema):
    quotations = QuotationList()


class BillSchema(ExtendedMappingSchema):
    id = UUID(description="Bill ID.")
    title = ExtendedSchemaNode(String(), description="Name of the bill.")
    description = ExtendedSchemaNode(String(), missing=drop)
    price = ExtendedSchemaNode(Float(), description="Price associated to the bill.")
    currency = ExtendedSchemaNode(String(), description="Currency code in ISO-4217 format.")
    created = ExtendedSchemaNode(DateTime(), description="Creation date and time of the bill in ISO-8601 format.")
    userId = ExtendedSchemaNode(Integer(), description="User id that requested the quote.")
    quotationId = UUID(description="Corresponding quote ID.", missing=drop)


class BillList(ExtendedSequenceSchema):
    item = ExtendedSchemaNode(String(), description="Bill ID.")


class BillListSchema(ExtendedMappingSchema):
    bills = BillList()


class SupportedValues(ExtendedMappingSchema):
    pass


class DefaultValues(ExtendedMappingSchema):
    pass


class CWLClass(ExtendedSchemaNode):
    schema_type = String
    title = "Class"
    name = "class"
    example = "CommandLineTool"
    validator = OneOf(["CommandLineTool", "ExpressionTool", "Workflow"])
    description = "CWL class specification. This is used to differentiate between single Application Package (AP)" \
                  "definitions and Workflow that chains multiple packages."


class DockerRequirementSpecification(ExtendedMappingSchema):
    dockerPull = URL(example="docker-registry.host.com/namespace/image:1.2.3",
                     description="Reference package that will be retrieved and executed by CWL.")


class DockerRequirement(VariableMappingSchema):
    DockerRequirement = DockerRequirementSpecification(title="DockerRequirement")


class CWLRequirement(OneOfKeywordSchema):
    _one_of = (DockerRequirement, )


class CWLRequirementList(ExtendedSequenceSchema):
    requirement = CWLRequirement()


class CWLRequirementsSpecification(VariableMappingSchema):
    requirements = CWLRequirementList()


class CWLHintsSpecification(VariableMappingSchema):
    hints = CWLRequirementList()


class CWLRequirementReferences(OneOfKeywordSchema):
    _one_of = [
        CWLRequirementsSpecification(description="Explicit requirement to execute the application package."),
        CWLHintsSpecification(description="Additional hints listing that could help resolve extra requirement.")
    ]


class CWLArguments(ExtendedSequenceSchema):
    argument = ExtendedSchemaNode(String())


# Note: can be very different schemas, this is enough doc for Weaver purpose, don't go in full details
class CWLInput(VariableMappingSchema):
    id = ExtendedSchemaNode(String())
    _type = ExtendedSchemaNode(name="type")
    inputBinding = ExtendedMappingSchema(missing=drop, description="Defines how to specify the input for the command.")
    default = ValueTypeFormats(missing=drop)


class OutputBinding(VariableMappingSchema):
    glob = ExtendedSchemaNode(description="Glob pattern the will find the output on disk or mounted docker volume.")


class CWLOutput(VariableMappingSchema):
    id = ExtendedSchemaNode(String())
    _type = ExtendedSchemaNode(name="type")
    outputBinding = OutputBinding(description="Defines how to retrieve the output result from the command.")


class CWLInputList(ExtendedSequenceSchema):
    input = CWLInput(description="Input specification. " + CWL_DOC_MESSAGE)


class CWLOutputList(ExtendedSequenceSchema):
    input = CWLInput(description="Output specification. " + CWL_DOC_MESSAGE)


class CWL(VariableMappingSchema, CWLRequirementReferences):
    cwlVersion = Version(description="CWL version of the described application package.")
    _class = CWLClass()
    baseCommand = ExtendedSchemaNode(
        missing=drop,
        description="Command called in the docker image or on shell "
                    "according to requirements and hints specifications.")
    arguments = CWLArguments(description="Base arguments passed to the command.")
    inputs = CWLInputList(description="All inputs available to the Application Package.")
    outputs = CWLInputList(description="All outputs produced by the Application Package.")


class UnitType(ExtendedMappingSchema):
    unit = CWL(description="Execution unit definition as CWL package specification. " + CWL_DOC_MESSAGE)


class ProcessInputDescriptionSchema(ExtendedMappingSchema):
    minOccurs = ExtendedSchemaNode(Integer())
    maxOccurs = ExtendedSchemaNode(Integer())
    title = ExtendedSchemaNode(String())
    dataType = ExtendedSchemaNode(String())
    abstract = ExtendedSchemaNode(String())
    id = ExtendedSchemaNode(String())
    defaultValue = ExtendedSequenceSchema(DefaultValues())
    supportedValues = ExtendedSequenceSchema(SupportedValues())


class ProcessDescriptionSchema(ExtendedMappingSchema):
    outputs = ExtendedSequenceSchema(ProcessOutputDescriptionSchema())
    inputs = ExtendedSequenceSchema(ProcessInputDescriptionSchema())
    description = ExtendedSchemaNode(String())
    id = ExtendedSchemaNode(String())
    label = ExtendedSchemaNode(String())


class UndeploymentResult(ExtendedMappingSchema):
    id = ExtendedSchemaNode(String())


class DeploymentResult(ExtendedMappingSchema):
    processSummary = ProcessSummary()


class ProcessDescriptionBodySchema(ExtendedMappingSchema):
    process = ProcessDescriptionSchema()


class ProvidersSchema(ExtendedSequenceSchema):
    providers_service = ProviderSummarySchema()


class ProcessesSchema(ExtendedSequenceSchema):
    provider_processes_service = Process()


class JobOutput(OneOfKeywordSchema, OutputDataType):
    id = UUID(description="Job output id corresponding to process description outputs.")
    _one_of = (
        Reference,
        DataType
    )


class JobOutputList(ExtendedSequenceSchema):
    output = JobOutput(description="Job output result with specific keyword according to represented format.")


class JobResultValue(OutputDataType):
    value = ValueType(description="Job outputs result conforming to OGC standard.")


class JobException(ExtendedMappingSchema):
    # note: test fields correspond exactly to 'owslib.wps.WPSException', they are serialized as is
    Code = ExtendedSchemaNode(String())
    Locator = ExtendedSchemaNode(String(), default=None)
    Text = ExtendedSchemaNode(String())


class JobExceptionList(ExtendedSequenceSchema):
    exceptions = JobException()


class JobLogList(ExtendedSequenceSchema):
    log = ExtendedSchemaNode(String())


class FrontpageParameterSchema(ExtendedMappingSchema):
    name = ExtendedSchemaNode(String(), example="api")
    enabled = ExtendedSchemaNode(Boolean(), example=True)
    url = URL(description="Referenced parameter endpoint.", example="https://weaver-host", missing=drop)
    doc = ExtendedSchemaNode(String(), example="https://weaver-host/api", missing=drop)


class FrontpageParameters(ExtendedSequenceSchema):
    param = FrontpageParameterSchema()


class FrontpageSchema(ExtendedMappingSchema):
    message = ExtendedSchemaNode(String(), default="Weaver Information", example="Weaver Information")
    configuration = ExtendedSchemaNode(String(), default="default", example="default")
    parameters = FrontpageParameters()


class SwaggerJSONSpecSchema(ExtendedMappingSchema):
    pass


class SwaggerUISpecSchema(ExtendedMappingSchema):
    pass


class VersionsSpecSchema(ExtendedMappingSchema):
    name = ExtendedSchemaNode(String(), description="Identification name of the current item.", example="weaver")
    type = ExtendedSchemaNode(String(), description="Identification type of the current item.", example="api")
    version = Version(description="Version of the current item.", example="0.1.0")


class VersionsList(ExtendedSequenceSchema):
    item = VersionsSpecSchema()


class VersionsSchema(ExtendedMappingSchema):
    versions = VersionsList()


class ConformanceList(ExtendedSequenceSchema):
    item = URL(description="Conformance specification link.",
               example="http://www.opengis.net/spec/wfs-1/3.0/req/core")


class ConformanceSchema(ExtendedMappingSchema):
    conformsTo = ConformanceList()


#################################
# Local Processes schemas
#################################


class PackageBody(ExtendedMappingSchema):
    pass


class ExecutionUnit(OneOfKeywordSchema):
    _one_of = (Link, UnitType)


class ExecutionUnitList(ExtendedSequenceSchema):
    unit = ExecutionUnit()


class ProcessOffering(ExtendedMappingSchema):
    process = Process()
    processVersion = Version(title="processVersion", missing=drop)
    jobControlOptions = JobControlOptionsList(missing=drop)
    outputTransmission = TransmissionModeList(missing=drop)


class ProcessDescriptionChoiceType(OneOfKeywordSchema):
    _one_of = (Reference,
               ProcessOffering)


class Deploy(ExtendedMappingSchema):
    processDescription = ProcessDescriptionChoiceType()
    immediateDeployment = ExtendedSchemaNode(Boolean(), missing=drop, default=True)
    executionUnit = ExecutionUnitList()
    deploymentProfileName = ExtendedSchemaNode(String(), format="url", missing=drop)
    owsContext = OWSContext(missing=drop)


class PostProcessesEndpoint(ExtendedMappingSchema):
    header = Headers()
    body = Deploy(title="Deploy")


class PostProcessJobsEndpoint(ProcessPath):
    header = AcceptLanguageHeader()
    body = Execute()


class GetJobsQueries(ExtendedMappingSchema):
    detail = ExtendedSchemaNode(Boolean(), description="Provide job details instead of IDs.",
                        default=False, example=True, missing=drop)
    groups = ExtendedSchemaNode(String(), description="Comma-separated list of grouping fields with which to list jobs.",
                        default=False, example="process,service", missing=drop)
    page = ExtendedSchemaNode(Integer(), missing=drop, default=0)
    limit = ExtendedSchemaNode(Integer(), missing=drop, default=10)
    status = JobStatusEnum(missing=drop)
    process = ExtendedSchemaNode(String(), missing=drop, default=None)
    provider = ExtendedSchemaNode(String(), missing=drop, default=None)
    sort = JobSortEnum(missing=drop)
    tags = ExtendedSchemaNode(String(), missing=drop, default=None,
                      description="Comma-separated values of tags assigned to jobs")


class GetJobsRequest(ExtendedMappingSchema):
    header = Headers()
    querystring = GetJobsQueries()


class GetJobsEndpoint(GetJobsRequest):
    pass


class GetProcessJobsEndpoint(GetJobsRequest, ProcessPath):
    pass


class GetProviderJobsEndpoint(GetJobsRequest, ProviderPath, ProcessPath):
    pass


class GetProcessJobEndpoint(ProcessPath):
    header = Headers()


class DeleteProcessJobEndpoint(ProcessPath):
    header = Headers()


class BillsEndpoint(ExtendedMappingSchema):
    header = Headers()


class BillEndpoint(BillPath):
    header = Headers()


class ProcessQuotesEndpoint(ProcessPath):
    header = Headers()


class ProcessQuoteEndpoint(ProcessPath, QuotePath):
    header = Headers()


class GetQuotesQueries(ExtendedMappingSchema):
    page = ExtendedSchemaNode(Integer(), missing=drop, default=0)
    limit = ExtendedSchemaNode(Integer(), missing=drop, default=10)
    process = ExtendedSchemaNode(String(), missing=drop, default=None)
    sort = QuoteSortEnum(missing=drop)


class QuotesEndpoint(ExtendedMappingSchema):
    header = Headers()
    querystring = GetQuotesQueries()


class QuoteEndpoint(QuotePath):
    header = Headers()


class PostProcessQuote(ProcessPath, QuotePath):
    header = Headers()
    body = ExtendedMappingSchema(default={})


class PostQuote(QuotePath):
    header = Headers()
    body = ExtendedMappingSchema(default={})


class PostProcessQuoteRequestEndpoint(ProcessPath, QuotePath):
    header = Headers()
    body = QuoteProcessParametersSchema()


#################################
# Provider Processes schemas
#################################


class GetProviders(ExtendedMappingSchema):
    header = Headers()


class PostProvider(ExtendedMappingSchema):
    header = Headers()
    body = CreateProviderRequestBody()


class GetProviderProcesses(ExtendedMappingSchema):
    header = Headers()


class GetProviderProcess(ExtendedMappingSchema):
    header = Headers()


class PostProviderProcessJobRequest(ExtendedMappingSchema):
    """Launching a new process request definition."""
    header = Headers()
    querystring = LaunchJobQuerystring()
    body = Execute()


#################################
# Responses schemas
#################################

class ErrorDetail(ExtendedMappingSchema):
    code = ExtendedSchemaNode(Integer(), example=401)
    status = ExtendedSchemaNode(String(), example="401 Unauthorized.")


class ErrorJsonResponseBodySchema(ExtendedMappingSchema):
    code = ExtendedSchemaNode(String(), example="NoApplicableCode")
    description = ExtendedSchemaNode(String(), example="Not authorized to access this resource.")
    error = ErrorDetail(missing=drop)


class UnauthorizedJsonResponseSchema(ExtendedMappingSchema):
    header = Headers()
    body = ErrorJsonResponseBodySchema()


class OkGetFrontpageResponse(ExtendedMappingSchema):
    header = Headers()
    body = FrontpageSchema()


class OkGetSwaggerJSONResponse(ExtendedMappingSchema):
    header = Headers()
    body = SwaggerJSONSpecSchema(description="Swagger JSON of weaver API.")


class OkGetSwaggerUIResponse(ExtendedMappingSchema):
    header = HtmlHeader()
    body = SwaggerUISpecSchema(description="Swagger UI of weaver API.")


class OkGetVersionsResponse(ExtendedMappingSchema):
    header = Headers()
    body = VersionsSchema()


class OkGetConformanceResponse(ExtendedMappingSchema):
    header = Headers()
    body = ConformanceSchema()


class OkGetProvidersListResponse(ExtendedMappingSchema):
    header = Headers()
    body = ProvidersSchema()


class InternalServerErrorGetProvidersListResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during providers listing."


class OkGetProviderCapabilitiesSchema(ExtendedMappingSchema):
    header = Headers()
    body = ProviderCapabilitiesSchema()


class InternalServerErrorGetProviderCapabilitiesResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during provider capabilities request."


class NoContentDeleteProviderSchema(ExtendedMappingSchema):
    header = Headers()
    body = ExtendedMappingSchema(default={})


class InternalServerErrorDeleteProviderResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during provider removal."


class NotImplementedDeleteProviderResponse(ExtendedMappingSchema):
    description = "Provider removal not supported using referenced storage."


class OkGetProviderProcessesSchema(ExtendedMappingSchema):
    header = Headers()
    body = ProcessesSchema()


class InternalServerErrorGetProviderProcessesListResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during provider processes listing."


class GetProcessesQuery(ExtendedMappingSchema):
    providers = ExtendedSchemaNode(
        Boolean(), example=True, default=False, missing=drop,
        description="List local processes as well as all sub-processes of all registered providers. "
                    "Applicable only for Weaver in {} mode, false otherwise.".format(WEAVER_CONFIGURATION_EMS))
    detail = ExtendedSchemaNode(
        Boolean(), example=True, default=True, missing=drop,
        description="Return summary details about each process, or simply their IDs."
    )


class GetProcessesEndpoint(ExtendedMappingSchema):
    querystring = GetProcessesQuery()


class OkGetProcessesListResponse(ExtendedMappingSchema):
    header = Headers()
    body = ProcessCollection()


class InternalServerErrorGetProcessesListResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during processes listing."


class OkPostProcessDeployBodySchema(ExtendedMappingSchema):
    deploymentDone = ExtendedSchemaNode(Boolean(), description="Indicates if the process was successfully deployed.",
                                default=False, example=True)
    processSummary = ProcessSummary(missing=drop, description="Deployed process summary if successful.")
    failureReason = ExtendedSchemaNode(String(), missing=drop, description="Description of deploy failure if applicable.")


class OkPostProcessesResponse(ExtendedMappingSchema):
    header = Headers()
    body = OkPostProcessDeployBodySchema()


class InternalServerErrorPostProcessesResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during process deployment."


class OkGetProcessInfoResponse(ExtendedMappingSchema):
    header = Headers()
    body = ProcessOffering()


class InternalServerErrorGetProcessResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during process description."


class OkGetProcessPackageSchema(ExtendedMappingSchema):
    header = Headers()
    body = ExtendedMappingSchema(default={})


class InternalServerErrorGetProcessPackageResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during process package description."


class OkGetProcessPayloadSchema(ExtendedMappingSchema):
    header = Headers()
    body = ExtendedMappingSchema(default={})


class InternalServerErrorGetProcessPayloadResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during process payload description."


class ProcessVisibilityResponseBodySchema(ExtendedMappingSchema):
    value = ExtendedSchemaNode(String(), validator=OneOf(list(VISIBILITY_VALUES)), example=VISIBILITY_PUBLIC)


class OkGetProcessVisibilitySchema(ExtendedMappingSchema):
    header = Headers()
    body = ProcessVisibilityResponseBodySchema()


class InternalServerErrorGetProcessVisibilityResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during process visibility retrieval."


class OkPutProcessVisibilitySchema(ExtendedMappingSchema):
    header = Headers()
    body = ProcessVisibilityResponseBodySchema()


class InternalServerErrorPutProcessVisibilityResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during process visibility update."


class OkDeleteProcessUndeployBodySchema(ExtendedMappingSchema):
    deploymentDone = ExtendedSchemaNode(Boolean(), default=False, example=True,
                                        description="Indicates if the process was successfully undeployed.")
    identifier = ExtendedSchemaNode(String(), example="workflow")
    failureReason = ExtendedSchemaNode(String(), missing=drop,
                                       description="Description of undeploy failure if applicable.")


class OkDeleteProcessResponse(ExtendedMappingSchema):
    header = Headers()
    body = OkDeleteProcessUndeployBodySchema()


class InternalServerErrorDeleteProcessResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during process deletion."


class OkGetProviderProcessDescriptionResponse(ExtendedMappingSchema):
    header = Headers()
    body = ProcessDescriptionBodySchema()


class InternalServerErrorGetProviderProcessResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during provider process description."


class CreatedPostProvider(ExtendedMappingSchema):
    header = Headers()
    body = ProviderSummarySchema()


class InternalServerErrorPostProviderResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during provider process registration."


class NotImplementedPostProviderResponse(ExtendedMappingSchema):
    description = "Provider registration not supported using referenced storage."


class CreatedLaunchJobResponse(ExtendedMappingSchema):
    header = Headers()
    body = CreatedJobStatusSchema()


class InternalServerErrorPostProcessJobResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during process job submission."


class InternalServerErrorPostProviderProcessJobResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during process job submission."


class OkGetProcessJobResponse(ExtendedMappingSchema):
    header = Headers()
    body = JobStatusInfo()


class OkDeleteProcessJobResponse(ExtendedMappingSchema):
    header = Headers()
    body = DismissedJobSchema()


class OkGetQueriedJobsResponse(ExtendedMappingSchema):
    header = Headers()
    body = GetQueriedJobsSchema()


class InternalServerErrorGetJobsResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during jobs listing."


class OkDismissJobResponse(ExtendedMappingSchema):
    header = Headers()
    body = DismissedJobSchema()


class InternalServerErrorDeleteJobResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during job dismiss request."


class OkGetJobStatusResponse(ExtendedMappingSchema):
    header = Headers()
    body = JobStatusInfo()


class InternalServerErrorGetJobStatusResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during provider process description."


class Inputs(ExtendedMappingSchema):
    inputs = InputList()
    links = LinkList(missing=drop)


class OkGetJobInputsResponse(ExtendedMappingSchema):
    header = Headers()
    body = Inputs()


class Outputs(ExtendedMappingSchema):
    outputs = JobOutputList()
    links = LinkList(missing=drop)


class OkGetJobOutputsResponse(ExtendedMappingSchema):
    header = Headers()
    body = Outputs()


class Results(ExtendedSequenceSchema):
    """List of outputs obtained from a successful process job execution."""
    result = JobResultValue()


class OkGetJobResultsResponse(ExtendedMappingSchema):
    header = Headers()
    body = Results()  # list is returned directly without extra metadata, OGC-standard


class InternalServerErrorGetJobResultsResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during job results listing."


class InternalServerErrorGetJobOutputResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during job results listing."


class CreatedQuoteExecuteResponse(ExtendedMappingSchema):
    header = Headers()
    body = CreatedQuotedJobStatusSchema()


class InternalServerErrorPostQuoteExecuteResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during quote job execution."


class CreatedQuoteRequestResponse(ExtendedMappingSchema):
    header = Headers()
    body = QuoteSchema()


class InternalServerErrorPostQuoteRequestResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during quote submission."


class OkGetQuoteInfoResponse(ExtendedMappingSchema):
    header = Headers()
    body = QuoteSchema()


class InternalServerErrorGetQuoteInfoResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during quote retrieval."


class OkGetQuoteListResponse(ExtendedMappingSchema):
    header = Headers()
    body = QuotationListSchema()


class InternalServerErrorGetQuoteListResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during quote listing."


class OkGetBillDetailResponse(ExtendedMappingSchema):
    header = Headers()
    body = BillSchema()


class InternalServerErrorGetBillInfoResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during bill retrieval."


class OkGetBillListResponse(ExtendedMappingSchema):
    header = Headers()
    body = BillListSchema()


class InternalServerErrorGetBillListResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during bill listing."


class OkGetJobExceptionsResponse(ExtendedMappingSchema):
    header = Headers()
    body = JobExceptionList()


class InternalServerErrorGetJobExceptionsResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during job exceptions listing."


class OkGetJobLogsResponse(ExtendedMappingSchema):
    header = Headers()
    body = JobLogList()


class InternalServerErrorGetJobLogsResponse(ExtendedMappingSchema):
    description = "Unhandled error occurred during job logs listing."


get_api_frontpage_responses = {
    "200": OkGetFrontpageResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
}
get_api_swagger_json_responses = {
    "200": OkGetSwaggerJSONResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
}
get_api_swagger_ui_responses = {
    "200": OkGetSwaggerUIResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
}
get_api_versions_responses = {
    "200": OkGetVersionsResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
}
get_api_conformance_responses = {
    "200": OkGetConformanceResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized")
}
get_processes_responses = {
    "200": OkGetProcessesListResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetProcessesListResponse(),
}
post_processes_responses = {
    "201": OkPostProcessesResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorPostProcessesResponse(),
}
get_process_responses = {
    "200": OkGetProcessInfoResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetProcessResponse(),
}
get_process_package_responses = {
    "200": OkGetProcessPackageSchema(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetProcessPackageResponse(),
}
get_process_payload_responses = {
    "200": OkGetProcessPayloadSchema(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetProcessPayloadResponse(),
}
get_process_visibility_responses = {
    "200": OkGetProcessVisibilitySchema(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetProcessVisibilityResponse(),
}
put_process_visibility_responses = {
    "200": OkPutProcessVisibilitySchema(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorPutProcessVisibilityResponse(),
}
delete_process_responses = {
    "200": OkDeleteProcessResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorDeleteProcessResponse(),
}
get_providers_list_responses = {
    "200": OkGetProvidersListResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetProvidersListResponse(),
}
get_provider_responses = {
    "200": OkGetProviderCapabilitiesSchema(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetProviderCapabilitiesResponse(),
}
delete_provider_responses = {
    "204": NoContentDeleteProviderSchema(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorDeleteProviderResponse(),
    "501": NotImplementedDeleteProviderResponse(),
}
get_provider_processes_responses = {
    "200": OkGetProviderProcessesSchema(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetProviderProcessesListResponse(),
}
get_provider_process_responses = {
    "200": OkGetProviderProcessDescriptionResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetProviderProcessResponse(),
}
post_provider_responses = {
    "201": CreatedPostProvider(description="success"),
    "400": ExtendedMappingSchema(description=OWSMissingParameterValue.description),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorPostProviderResponse(),
    "501": NotImplementedPostProviderResponse(),
}
post_provider_process_job_responses = {
    "201": CreatedLaunchJobResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorPostProviderProcessJobResponse(),
}
post_process_jobs_responses = {
    "201": CreatedLaunchJobResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorPostProcessJobResponse(),
}
get_all_jobs_responses = {
    "200": OkGetQueriedJobsResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetJobsResponse(),
}
get_single_job_status_responses = {
    "200": OkGetJobStatusResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetJobStatusResponse(),
}
delete_job_responses = {
    "200": OkDismissJobResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorDeleteJobResponse(),
}
get_job_inputs_responses = {
    "200": OkGetJobInputsResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetJobResultsResponse(),
}
get_job_outputs_responses = {
    "200": OkGetJobOutputsResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetJobResultsResponse(),
}
get_job_results_responses = {
    "200": OkGetJobResultsResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetJobResultsResponse(),
}
get_exceptions_responses = {
    "200": OkGetJobExceptionsResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetJobExceptionsResponse(),
}
get_logs_responses = {
    "200": OkGetJobLogsResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetJobLogsResponse(),
}
get_quote_list_responses = {
    "200": OkGetQuoteListResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetQuoteListResponse(),
}
get_quote_responses = {
    "200": OkGetQuoteInfoResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetQuoteInfoResponse(),
}
post_quotes_responses = {
    "201": CreatedQuoteRequestResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorPostQuoteRequestResponse(),
}
post_quote_responses = {
    "201": CreatedQuoteExecuteResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorPostQuoteExecuteResponse(),
}
get_bill_list_responses = {
    "200": OkGetBillListResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetBillListResponse(),
}
get_bill_responses = {
    "200": OkGetBillDetailResponse(description="success"),
    "401": UnauthorizedJsonResponseSchema(description="unauthorized"),
    "500": InternalServerErrorGetBillInfoResponse(),
}


#################################################################
# Utility methods
#################################################################


def service_api_route_info(service_api, settings):
    api_base = wps_restapi_base_path(settings)
    return {"name": service_api.name, "pattern": "{base}{path}".format(base=api_base, path=service_api.path)}
