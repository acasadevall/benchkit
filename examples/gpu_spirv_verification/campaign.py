#!/usr/bin/env python3

# Copyright (C) 
# SPDX-License-Identifier: MIT

import multiprocessing

import pathlib
import json
from typing import Any, Dict, Iterable, List

from benchkit.campaign import CampaignCartesianProduct, CampaignSuite
from benchkit.platforms import Platform, get_remote_platform

# import SPIRV benchmark's campaign
from benchmarks.spirv_benchmark import SpirvBenchmark
from benchmarks.utils import reset_stty

# from benchmarks.config import *
from benchmarks import platforms_json_file, default_vars, default_litmus_tests

import argparse

remote_platforms = {}

def get_job_data() -> dict:
    def get_platforms() -> dict:
        global remote_platforms

        json_error = False

        # first try with json file to get remote platform info
        if pathlib.Path(platforms_json_file).exists():
            try:
                with open(platforms_json_file, 'r') as file:
                    remote_platforms = json.load(file)
            except FileNotFoundError as e:
                print(f"Error: '{platforms_json_file}' -> {e}")
                json_error = True
            except json.JSONDecodeError as e:
                print(f"Error: '{platforms_json_file}' -> {e}")
                json_error = True
            finally:
                if json_error:
                    print(f"Loaded {len(remote_platforms)} platforms from '{platforms_json_file}' data")
                    return remote_platforms
        else:
            json_error = True
        
        # if json cannot load or not exists, try with txt file "platforms.txt"
        if pathlib.Path("platforms.txt").exists() and json_error:
            with open("platforms.txt", 'r') as file:
                for line in file:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        key, value = re.line.split('=', 1)
                        remote_platforms[key.strip()] = value.strip()

        return remote_platforms

    remote_platforms = get_platforms()

    jobs_data = remote_platforms.get("jobs", None)

    job_groups = []

    if jobs_data is None:
        default_jobs = []

        for platform in remote_platforms.keys():
            default_data = {
                "platform" : remote_platforms[platform],
                "variables" : default_vars,
                "device" : 0,
                "litmus_tests" : default_litmus_tests
            }

            default_jobs.append(default_data)

        job_groups.append(default_jobs)

    else:
        if isinstance(jobs_data, dict):
            jobs_data = [jobs_data]

        for job_data in jobs_data:

            imported_jobs = []

            if isinstance(job_data, dict):
                job_data = [job_data]

            data_is_invalid = False
            for jd in job_data:
                platform = jd.get("platform", None)
                variables = jd.get("variables", None)
                device = jd.get("device", None)
                litmus_tests = jd.get("litmus_tests", None)

                platform = remote_platforms[platform] if platform in remote_platforms.keys() else None

                if platform is None:
                    data_is_invalid = True
                    continue # skip job  
                    
                new_data = {
                    "platform" : platform,
                    "variables" : default_vars if variables is None else variables,
                    "device" : 0 if device is None else device,
                    "litmus_tests" : default_litmus_tests if litmus_tests is None else litmus_tests
                }

                imported_jobs.append(new_data)

            if len(imported_jobs):
                job_groups.append(imported_jobs)

    return job_groups

# if not len(remote_platforms):
#     # hardcoded
#     remote_platforms = {
#         "gpu-research-nvidia" : "ssh://user@XX.XX.XX.XX:22",
#         "gpu-research-amd" : "ssh://user@XX.XX.XX.XX:22",
#         "gpu-research-intel" : "ssh://user@XX.XX.XX.XX:22"
#     }

def check_remote_platforms(all_jobs) -> bool:
    remote_map = { "platform" : None, "Devices" : [] }
    for p_id, jobs in enumerate(all_jobs):
        campaigns = []
        for job in jobs:
            curr_platform = job["platform"]
            device_info = job["device"]
            
            if curr_platform is None:
                continue # skip

            platform = get_remote_platform(curr_platform)

            spirv_benchmark = SpirvBenchmark(
                is_dry_run=True,
                platform=platform,
                device_info=device_info
            )

            print(spirv_benchmark.get_platform_gpu_devices(curr_platform))


@reset_stty
def main():

    parser = argparse.ArgumentParser("GPU Verification 'SPIRV' Campaign")
    parser.add_argument('-l', '--list', required=False, action='store_true', help="Show lits of jobs (and if remote SSH are available: TODO)")
    parser.add_argument('-n', '--dryrun', required=False, action='store_true', help="dryrun execution")
    parser.add_argument('-V', '--version', action='version', version='%(prog)s v0.1')
    args = parser.parse_args()

    is_dry_run = args.dryrun

    all_jobs = get_job_data()

    if args.list:
        check_remote_platforms(all_jobs)
        exit(0)
        # raise NotImplementedError("@TODO")

    if len(all_jobs) == 0:
        print("Cannot continue with empty jobs data ...")
        exit(1)

    # all_jobs = {
    #     "jobA" : {
    #             "platform" : remote_platforms["gpu-research-amd"],
    #             "variables" : gl_variables,
    #             "device" : "7800",
    #             "litmus_tests" : custom_tests
    #         },
    #     "jobB": {
    #             "platform" : remote_platforms["gpu-research-nvidia"],
    #             "variables" : gl_variables,
    #             "device" : "4060",
    #             "litmus_tests" : custom_tests
    #         },
    #     "jobC": {
    #             "platform" : remote_platforms["gpu-research-nvidia"],
    #             "variables" : gl_variables,
    #             "device" : "3060",
    #             "litmus_tests" : custom_tests,
    #             "barrier" : "jobB"
    #         }   
    #     # "jobD": 
    #     # {
    #     #     "platform" : remote_platforms["gpu-research-nvidia"],
    #     #     "variables" : gl_variables,
    #     #     "device" : 2,
    #     #     "litmus_tests" : custom_tests
    #     # }
    # }    

    campaign_suites = [None for p in range(len(all_jobs))]
    parallel_proc = [None for p in range(len(all_jobs))]

    # campaigns = []
    # for job_id in all_jobs.keys():
        # take parallelized job
        # job = all_jobs[job_id]
    
    for p_id, jobs in enumerate(all_jobs):

        campaigns = []
        for job in jobs:
            has_barrier = job.get("barrier", False) # @TODO: [JobA, seq(JobB,JobC), JobD]

            curr_platform = job["platform"]
            variables = job["variables"]
            litmus_tests = job["litmus_tests"]
            device_info = job["device"]
            
            if curr_platform is None:
                continue # skip

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

    csv_files = []
    for proc, campaign in zip(parallel_proc, campaign_suites):
        if proc is not None and campaign is not None:
            csv_files.append(campaign.generate_global_csv(engine="c"))
    
    print(csv_files)

if __name__ == "__main__":
    main()
