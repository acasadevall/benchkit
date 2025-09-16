#!/usr/bin/env python3

# Copyright (C) 
# SPDX-License-Identifier: MIT

import multiprocessing
import pathlib
import json
from typing import Any, Dict, Iterable, List
import re
import argparse
import sys

from benchkit.campaign import CampaignCartesianProduct, CampaignSuite
from benchkit.platforms import Platform, get_remote_platform

# import SPIRV benchmark's campaign
from benchmarks.spirv_benchmark import SpirvBenchmark, VulkanPlatformUtils, gpu_verification_script
from benchmarks.utils import reset_stty
from benchmarks.config import *

remote_platforms = {}

def get_job_data() -> dict:
    def get_platforms() -> dict:
        global remote_platforms

        json_error = False

        # first try with json file to get remote platform info
        if pathlib.Path(platforms_json_file).exists():
            try:
                with open(platforms_json_file, 'r') as file:
                    json_data = json.load(file)
            except FileNotFoundError as e:
                print(f"Error: '{platforms_json_file}' -> {e}")
                json_error = True
            except json.JSONDecodeError as e:
                print(f"Error: '{platforms_json_file}' -> {e}")
                json_error = True
            finally:
                if not json_error:
                    if bool(remote_platforms := json_data.get("platforms", {})) is True:
                        print(f"Loaded {len(remote_platforms)} platforms from '{platforms_json_file}' data")
                        return json_data
        else:
            json_error = True
        
        # if json cannot load or not exists, try with txt file "platforms.txt"
        if pathlib.Path("platforms.txt").exists() and (json_error or bool(remote_platforms) is False):
            with open("platforms.txt", 'r') as file:
                for line in file:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        remote_platforms[key.strip()] = value.strip()
            if bool(remote_platforms) is True:
                print(f"Loaded {len(remote_platforms)} platforms from 'platforms.txt'")
                return json_data

        print(pathlib.Path("platforms.txt").exists())
        
        return {}

    json_data = get_platforms()
    
    jobs_data = get_dynamic_job_data() if use_dynamic_job_data else json_data.get("jobs", None)
    
    job_groups = []

    if jobs_data is None:
        default_jobs = []

        for hostname in remote_platforms.keys():
            default_data = {
                "hostname" : hostname,
                "platform" : remote_platforms[hostname],
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
                hostname = jd.get("platform", None)
                variables = jd.get("variables", None)
                device = jd.get("device", None)
                litmus_tests = jd.get("litmus_tests", None)

                platform = remote_platforms[hostname] if hostname in remote_platforms.keys() else None

                if platform is None:
                    data_is_invalid = True
                    print(f"Job with unspecified platform has found: {hostname}")
                    continue # skip job  
                    
                new_data = {
                    "hostname" : hostname,
                    "platform" : platform,
                    "variables" : default_vars if variables is None else variables,
                    "device" : 0 if device is None else device,
                    "litmus_tests" : default_litmus_tests if litmus_tests is None else litmus_tests
                }

                imported_jobs.append(new_data)

            if len(imported_jobs):
                job_groups.append(imported_jobs)

    return job_groups

def check_remote_platforms(jobs: dict) -> bool:
    map_hostname_remote_jobs = {}

    map_hostname_platforms = { j.get("hostname", None) : j.get("platform", None) for job in jobs for j in job }
    map_hostname_devices = {}

    # add existing remote platforms for the check list process even if there are no jobs for it
    non_job_platform = {}
    for k, v in remote_platforms.items():
        if not k in map_hostname_platforms.keys():
            non_job_platform[k] = v
            map_hostname_platforms[k] = v

    all_non_job_devices = {}
    for hostname, platform in map_hostname_platforms.items():
        if hostname is not None and platform is not None:
            curr_remote_platform = get_remote_platform(platform)
            list_vk_devices = VulkanPlatformUtils.get_platform_gpu_devices(platform=curr_remote_platform)
            dict_platform_vk_devices = dict(zip(list(range(len(list_vk_devices))), list_vk_devices))
            map_hostname_devices[hostname] = dict_platform_vk_devices
            all_non_job_devices[hostname] = [dict_platform_vk_devices[k].strip() for k, v in dict_platform_vk_devices.items() if not "export" in v.lower()]
    
    all_platforms_available = True
    for p_id, job in enumerate(jobs):
        campaigns = []
        for j in job:
            hostname = j["hostname"]
            platform = j["platform"]
            device_info = j["device"]
            
            if platform is None:
                map_hostname_remote_jobs[hostname] = None
                continue # skip job

            dict_platform_vk_devices = {}
            if hostname in map_hostname_devices.keys():
                dict_platform_vk_devices = map_hostname_devices[hostname]
            else:
                # try to fetch platform
                curr_remote_platform = get_remote_platform(platform)
                list_vk_devices = VulkanPlatformUtils.get_platform_gpu_devices(platform=curr_remote_platform)
                dict_platform_vk_devices = dict(zip(list(range(len(list_vk_devices))), list_vk_devices))
                
                if list_vk_devices is None or len(list_vk_devices) == 0:
                    self.curr_logger.error(f"No Vulkan device in platform: {platform}")
                    all_platforms_available &= False

            if not hostname in map_hostname_remote_jobs.keys():
                map_hostname_remote_jobs[hostname] = {}

            vk_device_names = [dict_platform_vk_devices[k].strip() for k, v in dict_platform_vk_devices.items() if not "export" in v.lower()]

            device_id = 0
            device_name = None

            if isinstance(device_info, int):
                device_id = device_info
            elif isinstance(device_info, str):
                device_name = device_info
            else:
                pass

            found_device_id = device_id
            found_device_name = device_name

            device_found = False
            if device_name is not None:
                for vk_id, vk_device_name in enumerate(vk_device_names):
                    if device_name in vk_device_name:
                        found_device_name = vk_device_name.strip()
                        found_device_id = vk_id
                        device_found = True
                        break

            else:
                if device_id in dict_platform_vk_devices.keys():
                    found_device_name = dict_platform_vk_devices[device_id].strip()
                    found_device_id = int(device_id)
                    device_found = True

            if device_found:
                map_hostname_remote_jobs[hostname][found_device_id] = {"name" : found_device_name, "found" : True}
                all_non_job_devices[hostname][found_device_id] = None
            else:
                map_hostname_remote_jobs[hostname][-1] = {"id" : found_device_id, "name" : found_device_name, "found" : False}


    print("\nUsed devices (with jobs associated to it)")
    for hostname in map_hostname_remote_jobs.keys():
        print(f"::{hostname}::")
        devices = map_hostname_remote_jobs[hostname]
        if devices is None:
            print(f"  - PLATFORM NOT FOUND")
        if len(devices) == 0:
            print(f"  - NO DEVICE(S) FOUND")

        for dev_id in devices.keys():
            if devices[dev_id]["found"]:
                print(f"  > Device {dev_id}: {devices[dev_id]['name']}")
            else:
                print(f"  > Device {devices[dev_id]['id']}: {devices[dev_id]['name']} - MISSING")
        print("")

    non_used_devices = [
        device
        for hostname, devices in all_non_job_devices.items()
        if hostname is not None and len(devices) > 0
        for device in devices if device is not None
    ]

    if len(non_used_devices):
        print("Non-used devices (without jobs associated to it)")
        for hostname, devices in all_non_job_devices.items():
            if hostname is None or len(devices) == 0:
                continue
            for dev_id, device in enumerate(devices):
                if device is None:
                    continue
                print(f"::{hostname}::")
                print(f"  > Device {dev_id}: {device}\n")

    return all_platforms_available

def clean_remote_platforms(jobs: dict) -> bool:
    map_hostname_remote_jobs = {}

    map_hostname_platforms = { j.get("hostname", None) : j.get("platform", None) for job in jobs for j in job }
    map_hostname_devices = {}

    # add existing remote platforms for the cleaning process even if there are no jobs for it
    for k, v in remote_platforms.items():
        if not k in map_hostname_platforms.keys():
            map_hostname_platforms[k] = v

    for hostname in map_hostname_platforms.keys():
        if hostname is not None:
            platform = map_hostname_platforms[hostname]
            if platform is not None:
                curr_remote_platform = get_remote_platform(platform)
                print(f"Cleaning ... {hostname}/{platform}")
                st = VulkanPlatformUtils.do_git_preparation(platform=curr_remote_platform, reset=True)

# @reset_stty(sys.stdin)
def main():

    parser = argparse.ArgumentParser("GPU Verification 'SPIRV Empirical Runtime' Campaign")
    parser.add_argument('-N', '--name', required=False, type=str, metavar='CAMPAIGN_NAME', default="cartesian_campaign", help="Set campaign name (default: cartesian_campaign)")
    parser.add_argument('-l', '--list', required=False, action='store_true', help="Show list of remote platforms available based on jobs to run (do not execute)")
    parser.add_argument('-f', '--force', required=False, action='store_true', help="Force jobs to regenerate all litmus tests in remote platforms")
    parser.add_argument('-c', '--clean', required=False, action='store_true', help="Clean remote platforms files before running campaigns (binaries, generated files, etc.)")
    parser.add_argument('-r', '--run', required=False, action='store_true', help="Run campaign. Use it when combined with other flags like '--clean'. Example: ./campaign.py --clean -r")
    parser.add_argument('--no-update', required=False, action='store_true', help="No update from remote, use latests fetched version (if exists). Useful when git remote is not accessible")
    parser.add_argument('-n', '--dryrun', required=False, action='store_true', help="dryrun execution")
    parser.add_argument('-V', '--version', action='version', version='%(prog)s v0.1')
    args = parser.parse_args()

    campaign_name = args.name
    is_dry_run = args.dryrun
    do_force_tests = args.force
    do_list = args.list
    do_clean = args.clean
    do_run = args.run
    do_update = False if args.no_update else True

    print(f"Campaign name: {campaign_name}")
    all_jobs = get_job_data()

    if do_list:
        check_remote_platforms(jobs=all_jobs)
        exit(0)

    if do_clean:
        clean_remote_platforms(jobs=all_jobs)
        if not do_run:
            exit(0)

    if len(all_jobs) == 0:
        print("Cannot continue with empty jobs data ...")
        exit(1)

    campaign_suites = [None for p in range(len(all_jobs))]
    parallel_proc = [None for p in range(len(all_jobs))]
    
    for p_id, jobs in enumerate(all_jobs):
        dict_campaigns = [{"hostname" : None, "campaign" : None}]
        for job in jobs:
            hostname = job["hostname"]
            curr_platform = job["platform"]
            variables = job["variables"]
            litmus_tests = job["litmus_tests"]
            device_info = job["device"]

            if curr_platform is None:
                continue # skip

            platform = get_remote_platform(curr_platform)

            spirv_benchmark = SpirvBenchmark(
                is_dry_run=is_dry_run,
                platform=platform,
                device_info=device_info,
                litmus_tests=litmus_tests,
                variables=variables,
                re_generate_always=do_force_tests,
                update_from_remote=do_update,
            )

            if spirv_benchmark.ill_formed:
                continue # skip

            campaign = CampaignCartesianProduct(
                name=campaign_name,
                benchmark=spirv_benchmark,
                nb_runs=1,
                variables=variables,
                constants={},
                debug=False,
                gdb=False,
                enable_data_dir=True,
                benchmark_duration_seconds=None
            )

            dict_campaigns.append({
                "hostname" : hostname,
                "campaign" : campaign
                })

        hostnames = set([dict_c['hostname'] for dict_c in dict_campaigns if dict_c['hostname'] is not None])
        campaigns = [dict_c['campaign'] for dict_c in dict_campaigns if dict_c['campaign'] is not None]

        if len(campaigns):
            hostname = list(hostnames)[0] if len(hostnames) == 1 else "gpu-mixed-campaign"
            suite = CampaignSuite(campaigns=campaigns, external_ownership=True) # multiple processes
            suite.print_durations()
            campaign_suites[p_id] = {"hostname" : hostname, "suite" : suite}
            parallel_proc[p_id] = multiprocessing.Process(target=lambda: suite.run_suite(parallel=False))
            parallel_proc[p_id].start() # start CampaignSuite
    
    for proc in parallel_proc:
        if proc is not None:
            proc.join()
    
    if is_dry_run:
        return

    csv_files = []
    for p_id, (proc, campaign_suite) in enumerate(zip(parallel_proc, campaign_suites)):
        hostname = campaign_suite.get('hostname', p_id)
        suite = campaign_suite.get('suite', None)
        if proc is not None and suite is not None:
            csv_files.append(suite.generate_global_csv(engine="c", parent=hostname))

    # simply print generated global csv files
    print("\n\nList of generated global CSV files:")
    for f in csv_files:
        print(f"- {f.resolve()}")
    
    # print post-process command
    csv_files_n = ' '.join(str(p.resolve()) for p in csv_files)
    print(f"\n$ python3 {gpu_verification_script} {csv_files_n}")

if __name__ == "__main__":
    main()
