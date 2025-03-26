#!/usr/bin/env python3

# Copyright (C) 
# SPDX-License-Identifier: MIT

import multiprocessing

import pathlib
from typing import Any, Dict, Iterable, List

from benchkit.campaign import CampaignCartesianProduct, CampaignSuite
from benchkit.platforms import Platform, get_remote_platform

# import SPIRV benchmark's campaign
from benchmarks.spirv_benchmark import SpirvBenchmark
from benchmarks.utils import reset_stty

import argparse

remote_platforms = {
    "gpu-reserach-nvidia" : "ssh://acasadevall@XX.XX.XX.XX:22",
    "gpu-reserach-amd" : "ssh://acasadevall@XX.XX.XX.XX:22",
    "gpu-reserach-intel" : "ssh://acasadevall@XX.XX.XX.XX:22"
}

bs = [wg*sg*s for wg in [4,8,16,32] for sg in [8,16] for s in [32]]

# other tests
custom_tests = [
    "atomic/iriw",
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

@reset_stty
def main():

    parser = argparse.ArgumentParser("GPU Verification 'SPIRV' Campaign")
    parser.add_argument('-l', '--list', required=False, action='store_true', help="Show lits of jobs (and if remote SSH are available: TODO)")
    parser.add_argument('-n', '--dryrun', required=False, action='store_true', help="dryrun execution")
    parser.add_argument('-V', '--version', action='version', version='%(prog)s v0.1')
    args = parser.parse_args()

    is_dry_run = args.dryrun
    
    if args.list:
        raise NotImplementedError("@TODO")

    all_jobs_v2 = [
        [
            {
                "platform" : remote_platforms["gpu-reserach-amd"],
                "variables" : gl_variables,
                "device" : "7800",
                "litmus_tests" : custom_tests
            }
        ],
        [
            {
                "platform" : remote_platforms["gpu-reserach-nvidia"],
                "variables" : gl_variables,
                "device" : "4060",
                "litmus_tests" : custom_tests
            },
            {
                "platform" : remote_platforms["gpu-reserach-nvidia"],
                "variables" : gl_variables,
                "device" : "3060",
                "litmus_tests" : custom_tests,
                "barrier" : "jobB"
            }   
        ],
        [
            {
                "platform" : remote_platforms["gpu-reserach-intel"],
                "variables" : gl_variables,
                "device" : "A750",
                "litmus_tests" : custom_tests
            }
        ],
    ]

    all_jobs = {
        "jobA" : {
                "platform" : remote_platforms["gpu-reserach-amd"],
                "variables" : gl_variables,
                "device" : "7800",
                "litmus_tests" : custom_tests
            },
        "jobB": {
                "platform" : remote_platforms["gpu-reserach-nvidia"],
                "variables" : gl_variables,
                "device" : "4060",
                "litmus_tests" : custom_tests
            },
        "jobC": {
                "platform" : remote_platforms["gpu-reserach-nvidia"],
                "variables" : gl_variables,
                "device" : "3060",
                "litmus_tests" : custom_tests,
                "barrier" : "jobB"
            }   
        # "jobD": 
        # {
        #     "platform" : remote_platforms["gpu-reserach-nvidia"],
        #     "variables" : gl_variables,
        #     "device" : 2,
        #     "litmus_tests" : custom_tests
        # }
    }    

    campaign_suites = [None for p in range(len(all_jobs_v2))]
    parallel_proc = [None for p in range(len(all_jobs_v2))]

    # campaigns = []
    # for job_id in all_jobs.keys():
        # take parallelized job
        # job = all_jobs[job_id]
    
    for p_id, jobs in enumerate(all_jobs_v2):

        campaigns = []
        for job in jobs:
            has_barrier = job.get("barrier", False) # @TODO: [JobA, seq(JobB,JobC), JobD]

            curr_platform = job["platform"]
            variables = job["variables"]
            litmus_tests = job["litmus_tests"]
            device_info = job["device"]
            
            platform = get_remote_platform(curr_platform)

            # if not has_barrier:

            spirv_benchmark = SpirvBenchmark(
                is_dry_run=is_dry_run,
                platform=platform,
                device_info=device_info,
                litmus_tests=litmus_tests,
                variables=variables
            )

            if spirv_benchmark.ill_formed:
                continue # skip

            campaign = CampaignCartesianProduct(
                name="cartesian_campaign",
                benchmark=spirv_benchmark,
                nb_runs=1,
                variables=variables,
                constants={},
                debug=False,
                gdb=False,
                enable_data_dir=True,
                benchmark_duration_seconds=None
            )

            campaigns.append(campaign)

        if len(campaigns):
            suite = CampaignSuite(campaigns=campaigns)
            suite.print_durations()
            parallel_proc[p_id] = multiprocessing.Process(target=lambda: suite.run_suite(parallel=False))
            parallel_proc[p_id].start() # start CampaignSuite
            campaign_suites[p_id] = suite
        
        # suite.run_suite(parallel=False)
        # suite.generate_global_csv(engine="c")
    
    for proc in parallel_proc:
        if proc is not None:
            proc.join()

    for proc, campaign in zip(parallel_proc, campaign_suites):
        if proc is not None and campaign is not None:
            pass
            # campaign.generate_global_csv(engine="c")     

if __name__ == "__main__":
    main()
