bs = [wg*sg*s for wg in [4,8,16,32] for sg in [8,16] for s in [32]]

# other tests
custom_tests = [
    # "atomic/iriw",
    "mp-[diff-wg]-[sb-sb]_WwgRelSun-WwgRelSunwg_RwgAcqSunwg-RwgAcqSun",
    "mp-[same-wg]-[sb-sb]_WdvRelSunSav-WdvRelSwg_RdvAcqSwg-RdvAcqSunSvis"
]

test_definitions = {
    "MP" : [
        "atomic/mp",
        "mixed/mp",
        "plain/mp",
    ],
    "SB" : [
        "atomic/sb",
        "mixed/sb",
        "plain/sb",
    ]
    # ...
}

gl_variables={
    "block_size" : [min(bs)],
    "total_space" : [(1<<10)*1023],
    "test_repetitions" : [10],
    "shuffle_wg" : [False],
    "shuffle_sg" : [False],
    "wg_num" : [4,8,16,32],
    "sg_num" : [8,16],
    "sg_size" : [32],
    "sg_stress_num" : [0],
}

# gl_variables={
#     "block_size" : [min(bs)],
#     "total_space" : [(1<<10)*1023],
#     "test_repetitions" : [10],
#     "shuffle_wg" : [False],
#     "shuffle_sg" : [False],
#     "wg_num" : [4],
#     "sg_num" : [8],
#     "sg_size" : [32],
#     "sg_stress_num" : [0],
# }

remote_platforms = {
        "gpu-research-nvidia" : "ssh://username@ip:22",
    "gpu-research-amd" : "ssh://username@ip:22",
    "gpu-research-intel" : "ssh://username@ip:22"
}

custom_jobs = [
    [
        {
            "platform" : remote_platforms.get("gpu-research-amd", None),
            "variables" : gl_variables,
            "device" : "7800",
            "litmus_tests" : custom_tests
        }
    ],
    [
        {
            "platform" : remote_platforms.get("gpu-research-nvidia", None),
            "variables" : gl_variables,
            "device" : "4060",
            "litmus_tests" : custom_tests
        },
        {
            "platform" : remote_platforms.get("gpu-research-nvidia", None),
            "variables" : gl_variables,
            "device" : "3060",
            "litmus_tests" : custom_tests,
            "barrier" : "jobB"
        }   
    ],
    [
        {
            "platform" : remote_platforms.get("gpu-research-intel", None),
            "variables" : gl_variables,
            "device" : "A750",
            "litmus_tests" : custom_tests
        }
    ],
]
