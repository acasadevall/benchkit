platforms_json_file = "config.json"

default_vars = {
    "block_size" : [(1<<10), (1<<10)*128],
    "total_space" : [(1<<10)*1023],
    "test_repetitions" : [10],
    "shuffle_wg" : [False],
    "shuffle_sg" : [False],
    "wg_num" : [4,8],
    "sg_num" : [8,16],
    "sg_size" : [32],
    "sg_stress_num" : [2]
}

# default_vars = {
#     "block_size" : [(1<<10)*128],
#     "total_space" : [(1<<10)*1023],
#     "test_repetitions" : [10],
#     "shuffle_wg" : [False],
#     "shuffle_sg" : [False],
#     "wg_num" : [8],
#     "sg_num" : [16],
#     "sg_size" : [32],
#     "sg_stress_num" : [0]
# }

default_litmus_tests = {
    "default/atomic",
    "default/plain",
    "default/mixed",
}
# default_litmus_tests = {
#     "mp-[diff-wg]-[sb-sb]_WwgRelSun-WwgRelSunwg_RwgAcqSunwg-RwgAcqSun",
#     "mp-[same-wg]-[sb-sb]_WdvRelSunSav-WdvRelSwg_RdvAcqSwg-RdvAcqSunSvis"
# }

