{
    "cwlVersion": "v1.0",
    "class": "CommandLineTool",
    "hints": {
        "ESGF-CWTRequirement": {
            "provider": "https://aims2.llnl.gov/wps/",
            "process": "CDAT.aggregate"
        }
    },
    "inputs": {
        "files": {
            "type": {
                "type": "array",
                "items": "File"
            }
        },
        "variable": {
            "type": "string"
        },
        "api_key": {
            "type": "string"
        }
    },
    "outputs": {
        "output_netcdf": {
            "outputBinding": {
                "glob": "output_netcdf.nc"
            },
            "type": "File"
        }
    }
}