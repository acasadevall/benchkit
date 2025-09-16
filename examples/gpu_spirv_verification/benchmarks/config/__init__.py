##############################################
# Config campaign parameters
##############################################

# json file name `examples/gpu_spirv_verification` root dir
platforms_json_file = "config.json"

# use if no key `variables` is found in json job data
default_vars = {
    # "block_size" : [4096, 65536],
    # "total_space" : [131072],
    # "block_size" : [4096, 8192],
    "block_size" : [8192],
    "total_space" : [8192],
    "sg_stress_num" : [2],
    "test_repetitions" : [20],
    "sg_size" : [32],
    "test_type" : ["baseline", "stress", "stress-sg.sync"] # "baseline", "stress", "stress-sg", "stress-sg.sync"
}

# use if no key `litmus_tests` is found in json job data
# note: empty means all tests
default_litmus_tests = []

# if use_init_jobs = True, the `get_dynamic_job_data()` below will be used
# otherwise jobs described in `platforms_json_file` json file name are used
use_dynamic_job_data = False

##############################################
##############################################

def get_dynamic_job_data():

    bs = [wg*sg*s for wg in [4,8,16,32] for sg in [8,16] for s in [32]]

    # other tests (examples)
    custom_tests = [
        # "MP_",
        # "SB_",
        # "LB_",
        # "ASMO_",
        # "IRIW_",
        # "MP_DIFF-WG_SB-SB__W-.*-R"
    ]

    gl_variables = {
        "block_size" : [min(bs)],
        "total_space" : [(1<<10)*1023],
        "test_repetitions" : [10],
        "wg_num" : [4,8,16,32],
        "sg_num" : [8,16],
        "sg_size" : [32],
        "sg_stress_num" : [0],
    }

    jobs = [
        [
            {
                "platform" : "v100",
                "variables" : gl_variables,
                "litmus_tests" : custom_tests
            }
        ],
        [
            {
                "platform" : "gpu-research-nvidia",
                "variables" : gl_variables,
                "device" : "4060",
                "litmus_tests" : custom_tests
            },
            {
                "platform" : "gpu-research-nvidia",
                "variables" : gl_variables,
                "device" : "3060",
                "litmus_tests" : custom_tests
            }   
        ]
    ]

    return jobs
