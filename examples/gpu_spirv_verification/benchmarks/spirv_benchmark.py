# SPDX-License-Identifier: MIT

import git # TODO: replace with pythainer git + docker

import importlib
import shutil
from typing import Union  # For versions < 3.10
from benchmarks.utils.parser import my_parser
from benchmarks.utils import clean_up_ssh_connection, reset_stty

from benchkit.benchmark import Benchmark, CommandWrapper, CommandAttachment, SharedLib, PreRunHook, PostRunHook
from benchkit.platforms import Platform, get_current_platform, get_remote_platform
import pathlib
from benchkit.utils.dir import caller_dir

from typing import Any, Dict, List, Iterable

from benchkit.utils.types import Constants

import os, sys, shlex, re
import logging, functools
import datetime

_pylitmus_repo_url = 'https://github.com/natgavrilenko/pylitmus.git'
_pylitmus_repo_commit = 'subgroup-stress_exp'
_pylitmus_repo_clone_name = 'pylitmus-benchkit'

_accelerator_interface_repo_url = 'https://github.com/huawei-drc/accelerator-interface.git'
_accelerator_interface_repo_commit = "alignto_exp"
_accelerator_interface_repo_clone_name = 'accelerator-interface-benchkit'

_gpu_spirv_verification_repo_url = 'https://github.com/huawei-drc/gpu-verification.git'
_gpu_spirv_verification_repo_commit = "main"
_gpu_spirv_verification_repo_clone_name = 'gpu-verification-benchkit'

gpu_verification_script = f"/tmp/{_gpu_spirv_verification_repo_clone_name}/latest/spirv-empirical-runtime/test/scripts/export_data.py"

logging_verbosity=logging.INFO
logging.basicConfig(level=logging_verbosity)

logger = logging.getLogger(__name__)
# TODO: add custom handler somewhere in Benchkit rather than in SPIRV Benchmark ...
# logger.propagate = False # avoid propagating to root logger
# custom_console_handler = logging.StreamHandler()
# custom_console_handler.setFormatter(ExtraLogger('%(className)s%(funcName)s:%(levelname)s: %(message)s'))
# self.logger.addHandler(custom_console_handler)

def add_log(message=None):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            curr_logger = None
            if args and isinstance(args[0], object):
                # this is and obj method, called from class instnace
                self = args[0]
                curr_logger = getattr(self, 'logger', None)
            else:
                # not called from class
                self = None
            
            if curr_logger is None:
                curr_logger = logger if "logger" in globals() else None

            if curr_logger is None:
                return func(*args, **kwargs)
            else:
                _msg = func.__name__ if message is None else f"{func.__name__} - {message}"
                curr_logger.info(f"DO: {_msg}")
                ret = func(*args, **kwargs)
                curr_logger.info(f"DONE {func.__name__}")
                return ret
        return wrapper
    return decorator

gl_record_variables = []

class VulkanPlatformUtils:
    curr_logger = logger if "logger" in globals() else None
    set_hosts = set()

    # @clean_up_ssh_connection
    @add_log()
    @staticmethod
    def get_platform_gpu_devices(platform: Platform, gpu_vendor = None) -> List[str]:
        if platform is None:
            return
        
        gpu_source_script = f"gpu.source"
        gpu_source_script_path = pathlib.Path(f"~/{_gpu_spirv_verification_repo_clone_name}/spirv-empirical-runtime/test/scripts") / gpu_source_script
        gpu_source_cmd = "" if gpu_vendor is None else f". {gpu_source_script_path} {gpu_vendor} &&"

        list_vk_devices = platform.comm.shell(
            command=shlex.split(f"{gpu_source_cmd} vulkaninfo --summary 2> /dev/null | grep GPU -A10 | grep -oE 'deviceName.*' | cut -d '=' -f 2"),
            shell=True,
            print_input=False,
            print_output=False,
            output_is_log=False,            
        )
        if list_vk_devices.strip() == '':
            return 
        return list_vk_devices.strip().split('\n')

    @add_log()
    @staticmethod
    def get_platform_gpu_devices_json(platform: Platform, gpu_vendor = None) -> List[str]:
        if platform is None:
            return
        
        gpu_source_script = f"gpu.source"
        gpu_source_script_path = pathlib.Path(f"~/{_gpu_spirv_verification_repo_clone_name}/spirv-empirical-runtime/test/scripts") / gpu_source_script
        gpu_source_cmd = "" if gpu_vendor is None else f". {gpu_source_script_path} {gpu_vendor} &&"

        raw_vk_devices = platform.comm.shell(
            command=shlex.split(f"{gpu_source_cmd} vulkaninfo --summary 2> /dev/null | grep -E 'GPU[0-9]+:' -A12"),
            shell=True,
            print_input=False,
            print_output=False,
            output_is_log=False,            
        )
        if raw_vk_devices.strip() == '':
            return 
        list_vk_devices = raw_vk_devices.strip().split('\n')

        contents = []
        for lineno, line in enumerate(list_vk_devices):
            if (m := re.match(r'^GPU(\d+):', line)):
                contents.append([lineno, lineno])
            elif contents:
                contents[-1][1]+=1
            else:
                pass

        list_vk_devices_json = {}
        for l, line in enumerate(list_vk_devices):
            if len(line.strip()) == 0:
                continue
            gpu_match = re.match(r'^GPU(\d+):', line)
            if gpu_match:
                gpu_id = int(gpu_match.group(1))
                list_vk_devices_json[gpu_id] = {}

        for gpu_id, (b,e) in enumerate(contents):
            gpu_data = {d[0].strip(): d[1].strip() for data in list_vk_devices[b+1:e] if len((d := data.split('='))) == 2}
            if gpu_id in list_vk_devices_json.keys():
                list_vk_devices_json[gpu_id] = gpu_data

        return list_vk_devices_json

    @add_log()
    @staticmethod
    def do_git_repos_exist(platform: Platform, repo_clone_name: str, repo_commit: str = "main") -> bool:
        if platform is None:
            return

        git_status = True

        out = platform.comm.shell(
            command=shlex.split(f"cd ~/{repo_clone_name} && git status"),
            shell=True,
            print_input=False,
            print_output=False,
            output_is_log=False,
            ignore_any_error_code=True,
        )
        git_status &= False if "fatal" in out or "No such file or directory" in out else True

        return git_status

    @add_log()
    @staticmethod
    def do_git_preparation(platform: Platform, reset: bool = False, update_from_remote: bool = True, is_dry_run: bool = False) -> bool:
        def _precheck_repo(repo_url: str, repo_clone_name: str, repo_commit: str, requires_submodule: bool = False, output_dir: str = None) -> None:
            tmp_latest_repo = f"/tmp/{repo_clone_name}/latest"
            exists_repo = VulkanPlatformUtils.do_git_repos_exist(platform=platform, repo_clone_name=repo_clone_name, repo_commit=repo_commit)
        
            if exists_repo and not reset:
                update_host = True
                try:
                    # 1. check if remote project is already cloned in host
                    if pathlib.Path(tmp_latest_repo).is_dir():
                        repo = git.Repo(tmp_latest_repo)
                    else:
                        update_host = False
                except git.exc.InvalidGitRepositoryError:
                    update_host = False
                    VulkanPlatformUtils.curr_logger.error(f"InvalidGitRepositoryError: {e}")
                except Exception as e:
                    update_host = False
                    VulkanPlatformUtils.curr_logger.error(f"ERROR: {e}")
                finally:
                    if update_host:
                        # 2. If remote project exists in host, do a fit pull if `update_from_remote` is True
                        if update_from_remote:
                            VulkanPlatformUtils.curr_logger.info(f"Update from Remote: {repo_clone_name}/{repo_commit}")
                            repo.remotes.origin.fetch()
                            repo.git.checkout(repo_commit)
                            if requires_submodule:
                                repo.submodule_update(init=True, recursive=True) # `git submodule update --init --recursive`
                            origin = repo.remotes.origin
                            origin.pull()  # `git pull`

                        platform.comm.copy_from_host(pathlib.Path(tmp_latest_repo).resolve(), f"~/{'' if output_dir is None else output_dir}", print_output=False)

                        return
                    else:
                        # 3. If error during fetching/clone or `reset` is enabled, do git clone and copy again in next steps
                        pass
            
            # delete previous clones
            base = pathlib.Path(f"/tmp/{repo_clone_name}/")
            latest_clone = pathlib.Path(tmp_latest_repo)
            for p in base.glob(f"*/{repo_clone_name}"):
                if p.is_dir():
                    try:
                        if not p.samefile(latest_clone):
                            shutil.rmtree(p.parent)
                    except FileNotFoundError as e:
                        pass

            # a new git clone is required, create new folders & symlinks ...
            now = datetime.datetime.now(tz=datetime.timezone.utc)
            now_str = now.strftime("%Y%m%d_%H%M%S_%f")

            tmp_new_repo = f"/tmp/{repo_clone_name}/{now_str}/{repo_clone_name}"
            os.makedirs(tmp_new_repo)

            tmp_link = pathlib.Path(tmp_latest_repo)
            if tmp_link.is_symlink():
                tmp_link.unlink()
                
            tmp_link.symlink_to(tmp_new_repo) # create symlink

            repo = git.Repo.clone_from(repo_url, tmp_latest_repo)
            repo.git.checkout(repo_commit)
            if requires_submodule:
                repo.submodule_update(init=True, recursive=True) # `git submodule update --init --recursive`

            platform.comm.copy_from_host(pathlib.Path(tmp_latest_repo).resolve(), f"~/{'' if output_dir is None else output_dir}", print_output=False)
            return

        if platform is None:
            return

        if is_dry_run:
            return True
        
        # clean remote (possible) project
        if reset:
            VulkanPlatformUtils.curr_logger.info(f"Reset remote git: {_gpu_spirv_verification_repo_clone_name}/{_gpu_spirv_verification_repo_commit}")
            platform.comm.shell(
                command=shlex.split(f"rm -rf ~/{_gpu_spirv_verification_repo_clone_name} > /dev/null 2>&1"),
                shell=True,
                print_input=True,
                print_output=False,
                output_is_log=False,
                ignore_any_error_code=True,
            )
            VulkanPlatformUtils.curr_logger.info(f"Reset remote git: {_pylitmus_repo_clone_name}/{_pylitmus_repo_commit}")
            platform.comm.shell(
                command=shlex.split(f"rm -rf ~/{_pylitmus_repo_clone_name} > /dev/null 2>&1"),
                shell=True,
                print_input=True,
                print_output=False,
                output_is_log=False,
                ignore_any_error_code=True,
            )

        _precheck_repo(
            repo_url=_gpu_spirv_verification_repo_url,
            repo_clone_name=_gpu_spirv_verification_repo_clone_name,
            repo_commit=_gpu_spirv_verification_repo_commit,
            requires_submodule=False
        )

        _precheck_repo(
            repo_url=_pylitmus_repo_url,
            repo_clone_name=_pylitmus_repo_clone_name,
            repo_commit=_pylitmus_repo_commit,
            requires_submodule=False
        )

        _precheck_repo(
            repo_url=_accelerator_interface_repo_url,
            repo_clone_name=_accelerator_interface_repo_clone_name,
            repo_commit=_accelerator_interface_repo_commit,
            requires_submodule=False,
            output_dir=os.path.join(_gpu_spirv_verification_repo_clone_name, "spirv-empirical-runtime", "test")
        )

        return True

    # @clean_up_ssh_connection
    @add_log()
    @staticmethod
    def get_platform_existing_tests(platform: Platform) -> List[str]:
        #TODO: transform into something like "search for pylitmus tests"
        if platform is None:
            return []
        list_bin_tests = platform.comm.shell(
            command=shlex.split(f"find ~/{_gpu_spirv_verification_repo_clone_name}/spirv-empirical-runtime/build/bin -type f 2> /dev/null | grep vk_spirv_runtime"),
            shell=True,
            print_input=False,
            print_output=False,
            output_is_log=False,
            ignore_any_error_code=True    
        )
        if list_bin_tests.strip() == '':
            return []
        return list_bin_tests.strip().split('\n')

    # @clean_up_ssh_connection
    @add_log()
    @staticmethod
    def prepare_platform_tests(platform: Platform, benchmark_name: str|None = None, re_generate_is_needed: bool = False, is_dry_run: bool = False) -> bool:
        if platform is None:
            return False

        do_pylitmus_generation = False
        out = platform.comm.shell(
            command=shlex.split(f"ls ~/{_pylitmus_repo_clone_name}/generated && ls ~/{_pylitmus_repo_clone_name}/generated_sync"),
            shell=True,
            print_input=False,
            print_output=False,
            output_is_log=False,
            ignore_any_error_code=True
        )
        if "cannot access" in out:
            do_pylitmus_generation = True

        status = True
        if do_pylitmus_generation or (re_generate_is_needed and not platform.hostname in VulkanPlatformUtils.set_hosts):
            command = shlex.split(
                f"rm -rf ~/{_pylitmus_repo_clone_name}/templates ~/{_pylitmus_repo_clone_name}/templates* ~/{_pylitmus_repo_clone_name}/generated* 2> /dev/null; \
                python3 ~/{_pylitmus_repo_clone_name}/compilation/compilation.py --output ~/{_pylitmus_repo_clone_name}/templates && python3 ~/{_pylitmus_repo_clone_name}/compilation/compilation.py --output ~/{_pylitmus_repo_clone_name}/templates_sync --extra 'WAIT_FOR_STRESS' && \
                python3 ~/{_pylitmus_repo_clone_name}/generation/generation.py --templates ~/{_pylitmus_repo_clone_name}/templates --output ~/{_pylitmus_repo_clone_name}/generated && python3 ~/{_pylitmus_repo_clone_name}/generation/generation.py --templates ~/{_pylitmus_repo_clone_name}/templates_sync --output ~/{_pylitmus_repo_clone_name}/generated_sync"
            )

            # generate litmus tests for specific benchmark
            if is_dry_run:
                _cmd = " ".join(command)
                VulkanPlatformUtils.curr_logger.info(f"[DRYRUN] {_cmd}")
            else:
                status &= platform.comm.shell(
                    command=command,
                    shell=True,
                    print_input=True,
                    print_output=False,
                    output_is_log=True,
                ) == ""

            if status:
                VulkanPlatformUtils.set_hosts.add(platform.hostname)

        # f"\'for f in ~/pylitmus-benchkit/generated/*; do echo $f; find "$f"" -type f | grep \.spvasm$ > $f.tests; done'"
        command=shlex.split(
            f"rm ~/{_pylitmus_repo_clone_name}/*.tests 2> /dev/null; \
            for f in ~/{_pylitmus_repo_clone_name}/generated/*; do bs=$(basename \"$f\") && find \"$f\" -type f | grep \"\.spvasm$\" > \"~/{_pylitmus_repo_clone_name}/$bs.tests\"; done; \
            for f in ~/{_pylitmus_repo_clone_name}/generated/*; do bs=$(basename \"$f\") && find \"$f\" -type f | grep -E \"'MP_DIFF|ILLEGAL'\" > \"~/{_pylitmus_repo_clone_name}/$bs.minimal.tests\"; done; \
            for f in ~/{_pylitmus_repo_clone_name}/generated_sync/*; do bs=$(basename \"$f\") && find \"$f\" -type f | grep \"\.spvasm$\" > \"~/{_pylitmus_repo_clone_name}/$bs.sync.tests\"; done; \
            for f in ~/{_pylitmus_repo_clone_name}/generated_sync/*; do bs=$(basename \"$f\") && find \"$f\" -type f | grep -E \"'MP_DIFF|ILLEGAL'\" > \"~/{_pylitmus_repo_clone_name}/$bs.sync.minimal.tests\"; done",
            posix=True
        )
        if is_dry_run:
            _cmd = " ".join(command)
            VulkanPlatformUtils.curr_logger.info(f"[DRYRUN] {_cmd}")
        else:
            status &= platform.comm.shell(
                command=command,
                shell=True,
                print_input=True,
                print_output=False,
                output_is_log=True,
            ) == ""
        
        default_bin_exe = f"vk_spirv_runtime"
        custom_bin_exe = f"vk_spirv_runtime_{benchmark_name}"
        default_test_exec_bin_path = pathlib.Path(f"~/{_gpu_spirv_verification_repo_clone_name}/spirv-empirical-runtime/test/build/bin") / default_bin_exe
        custom_test_exec_bin_path = pathlib.Path(f"~/{_gpu_spirv_verification_repo_clone_name}/spirv-empirical-runtime/test/build/bin") / custom_bin_exe

        command = shlex.split(
            f"rm -rf ~/{_gpu_spirv_verification_repo_clone_name}/spirv-empirical-runtime/test/build/CMake* 2> /dev/null; cmake -B ~/{_gpu_spirv_verification_repo_clone_name}/spirv-empirical-runtime/test/build -S ~/{_gpu_spirv_verification_repo_clone_name}/spirv-empirical-runtime/test && \
            cmake --build ~/{_gpu_spirv_verification_repo_clone_name}/spirv-empirical-runtime/test/build --parallel; mv {default_test_exec_bin_path} {custom_test_exec_bin_path}",
            posix=True
        )
        build_status = True
        if is_dry_run:
            _cmd = " ".join(command)
            VulkanPlatformUtils.curr_logger.info(f"[DRYRUN] {_cmd}")
        else:
            build_status &= platform.comm.shell(
                command=command,
                shell=True,
                print_input=True,
                print_output=False,
                output_is_log=True,
            ) == ""
            
        return status and build_status != "" # TODO: we need status in comm shell ...

class SpirvBenchmark(Benchmark):
    """SPIRV Benchmark: memory model gpu-verification"""

    def __init__(
        self,
        command_wrappers: Iterable[CommandWrapper] = (),
        command_attachments: Iterable[CommandAttachment] = (),
        shared_libs: Iterable[SharedLib] = (),
        pre_run_hooks: Iterable[PreRunHook] = (),
        post_run_hooks: Iterable[PostRunHook] = (),
        platform: Platform = None,
        device_info: Union[int|str] = 0,
        litmus_tests: List[str] = None,
        is_dry_run: bool = False,
        re_generate_always: bool = False,
        update_from_remote: bool = True,
        variables: List[Any] = []
    ) -> None:
        global gl_record_variables

        super().__init__(
            command_wrappers=command_wrappers,
            command_attachments=command_attachments,
            shared_libs=shared_libs,
            pre_run_hooks=pre_run_hooks,
            post_run_hooks=post_run_hooks,
        )

        self.sel_vendor = None
        self.sel_device_name = None
        self.sel_device_id = None
        self.vulkan_sdk_version = "1.4.321.1" # match version with vulkan-sdk e.g., 1.4.321.1
        self.dict_platform_vk_devices = {}
        self.dict_platform_vk_devices_all = {}

        self.ill_formed = False
        self.update_from_remote = update_from_remote

        # ideally Benchmark.py or someone should have a logger
        curr_logger = getattr(self, 'logger', None)
        if curr_logger is None:
            self.curr_logger = logger if "logger" in globals() else None
        
        # if no loger is found, lets create a basic one
        if self.curr_logger is None:
            self.curr_logger = logging.getLogger(__name__)

        if platform is not None:
            self.platform = platform
        else:
            self.curr_logger.error("Platform is None!")
            self.ill_formed = True
            return

        list_vk_devices = VulkanPlatformUtils.get_platform_gpu_devices(platform=platform)
        if list_vk_devices is None or len(list_vk_devices) == 0:
            self.curr_logger.error(f"No Vulkan devices in platform!")
            self.ill_formed = True
            return

        # try to populate Vulkan info from platform and select triple vendor, devicename, deviceid
        if self.__populate_device_info(list_devices=list_vk_devices, device_info=device_info):
            self.curr_logger.info(f"Device selected (Vendor: {self.sel_vendor}, DeviceName: {self.sel_device_name}, DeviceID: {self.sel_device_id})")
        else:
            self.curr_logger.warning(f"Cannot populate device info correctly: Vendor: {self.sel_vendor}, DeviceName: {self.sel_device_name}, DeviceID: {self.sel_device_id}")
        
        platform_status = VulkanPlatformUtils.do_git_preparation(platform=platform, reset=False, update_from_remote=update_from_remote, is_dry_run=is_dry_run)
        if not platform_status:
            raise ValueError("Platform Git Error!")

        # set proper benchmark name based on platform/device name
        bm_name = " ".join(self.sel_device_name.strip().split()).replace(" ", "_").replace("(", "_").replace(")", "_")
        bm_name_2 = re.sub(r"[\[\]() ]", "_", " ".join(self.sel_device_name.strip().split()))
        assert bm_name == bm_name_2
        proposed_bm_name = f"benchkit_{bm_name}"

        VulkanPlatformUtils.prepare_platform_tests(platform=platform, benchmark_name=proposed_bm_name, re_generate_is_needed=re_generate_always, is_dry_run=is_dry_run)
        
        self.benchmark_name = proposed_bm_name
        self.litmus_tests = [litmus_tests] if not isinstance(litmus_tests, list) else litmus_tests
        self.variables = variables
        self.is_dry_run = is_dry_run

        gl_record_variables = variables

    def __populate_device_info(self, list_devices: List[str], device_info=int|str):
        def __look_up_devices():
            device_found = False
            if device_name is not None:
                vk_device_names = [self.dict_platform_vk_devices[k].strip() for k, v in self.dict_platform_vk_devices.items() if not "export" in v.lower()]
                for vk_id, vk_device_name in enumerate(vk_device_names):
                    if device_name in vk_device_name:
                        # get first matching id,name
                        self.sel_device_name = vk_device_name
                        self.sel_device_id = vk_id
                        device_found = True
                        break
            else:
                if device_id in self.dict_platform_vk_devices.keys():
                    self.sel_device_name = self.dict_platform_vk_devices[device_id]
                    self.sel_device_id = device_id
                    device_found = True

            if device_found == False:
                self.curr_logger.warning(f"DeviceID={device_id}/DeviceName={device_name} not found within available devices. Found devices: {self.dict_platform_vk_devices}")
                self.curr_logger.warning(f"DeviceID set to 0: {self.dict_platform_vk_devices[0]} (fallback default device)")
                self.sel_device_name = self.dict_platform_vk_devices[0]
                self.sel_device_id = 0

        def __search_for_vendor(target, names):
            for n in names:
                if n in self.sel_device_name.lower():
                    self.sel_vendor = target
                    return True
            return False

        device_id = 0
        device_name = None

        if isinstance(device_info, int):
            device_id = device_info
        elif isinstance(device_info, str):
            device_name = device_info
        else:
            pass

        if device_id < 0:
            self.curr_logger.error(f"{device_id} is not a valid device_id (device_id >= 0)")
            self.ill_formed = True
            return

        self.dict_platform_vk_devices = dict(zip(list(range(len(list_devices))), list_devices))
        __look_up_devices()

        st = False
        st |= __search_for_vendor("nvidia", ["rtx", "nvidia", "v100", "tesla"])
        st |= __search_for_vendor("amd", ["rx", "amd", "radeon"])
        st |= __search_for_vendor("intel", ["xe", "iris", "intel"])

        if st:
            new_list_vk_devices = VulkanPlatformUtils.get_platform_gpu_devices(platform=self.platform, gpu_vendor=self.sel_vendor)
            self.dict_platform_vk_devices = dict(zip(list(range(len(new_list_vk_devices))), new_list_vk_devices))
            __look_up_devices()

            self.dict_platform_vk_devices_all = VulkanPlatformUtils.get_platform_gpu_devices_json(platform=self.platform, gpu_vendor=self.sel_vendor)

        return st

    @property
    def bench_src_path(self) -> pathlib.Path:
        return caller_dir()

    @staticmethod
    def get_build_var_names() -> List[str]:
        return ["USE_VULKAN"]

    @staticmethod
    def get_run_var_names() -> List[str]:
        return gl_record_variables # this is a static method which cannot access self attributes ...
        # return [...vars...]

    def clean_bench(self) -> None:
        pass

    def prebuild_bench(
        self,
        **kwargs,
    ) -> int:
        self.platform.comm.makedirs(path="benchkit_benchmarks", exist_ok=True)
        return

    def build_bench(
        self,
        **kwargs,
    ) -> None:
        pass

    # @clean_up_ssh_connection
    # @reset_stty(sys.stdin)
    def single_run(
        self,
        constants: Constants = None,
        *args,
        **kwargs,
    ) -> str:
        def __reset_litmus_tests():
            return self.platform.comm.shell(
                command=shlex.split(
                    f"rm ~/{_pylitmus_repo_clone_name}/*.tmp.tests 2> /dev/null",
                    posix=True
                ),
                shell=True,
                print_input=True,
                print_output=False,
                output_is_log=False,
                ignore_any_error_code=True,
            ) == ""
        def __generate_litmus_tests(litmus_reg: str):
            return self.platform.comm.shell(
                command=shlex.split(
                    f"for f in ~/{_pylitmus_repo_clone_name}/generated/*; do bs=$(basename \"$f\") && find \"$f\" -type f | grep -E \"'{lt}'\" >> \"~/{_pylitmus_repo_clone_name}/$bs.tmp.tests\"; done; \
                    for f in ~/{_pylitmus_repo_clone_name}/generated_sync/*; do bs=$(basename \"$f\") && find \"$f\" -type f | grep -E \"'{lt}'\" >> \"~/{_pylitmus_repo_clone_name}/$bs.sync.tmp.tests\"; done",
                    posix=True
                ),
                shell=True,
                print_input=True,
                print_output=False,
                output_is_log=True,
            ) == ""

        runtime_test_variables = kwargs
        
        if len(runtime_test_variables) == 0:
            raise ValueError("No runtime test vars!")

        if (sel_dict := self.dict_platform_vk_devices_all.get(self.sel_device_id, None)) is not None:
            with open(self._csv_output_path, "a") as csv_output_file:
                self._log_extra_data(
                    output_file=csv_output_file,
                    extra_data=sel_dict
                )
        
        current_dir="~/"
 
        gpu_source_script = f"gpu.source"
        gpu_source_script_path = pathlib.Path(f"~/{_gpu_spirv_verification_repo_clone_name}/spirv-empirical-runtime/test/scripts") / gpu_source_script

        bin_exe = f"vk_spirv_runtime_{self.benchmark_name}"
        test_exec_bin_path = pathlib.Path(f"~/{_gpu_spirv_verification_repo_clone_name}/spirv-empirical-runtime/test/build/bin") / bin_exe
        
        test_type = runtime_test_variables.get('test_type', "baseline")
        stress_sg_num = runtime_test_variables.get('sg_stress_num', 0)
        if test_type == "stress-sg" and stress_sg_num > 0:
            stress_sg_num = stress_sg_num
            runtime_test_variables['sg_stress_num'] = stress_sg_num
        else:
            stress_sg_num = 0
            runtime_test_variables['sg_stress_num'] = 0

        # fallback will run complete tests
        # litmus_tests_fallback = f"~/{_pylitmus_repo_clone_name}/spirv-empirical-{test_type}.minimal.tests"
        litmus_tests_fallback = f"~/{_pylitmus_repo_clone_name}/spirv-empirical-{test_type}.tests"
        litmus_tests = [lt for lt in self.litmus_tests if lt.strip() != ""]

        status = True
        if len(litmus_tests) > 0:
            status &= __reset_litmus_tests()
            for lt in litmus_tests:
                status &= __generate_litmus_tests(litmus_reg=lt)
        
            litmus_tests = f"~/{_pylitmus_repo_clone_name}/spirv-empirical-{test_type}.tmp.tests"
        else:
            status = False
        
        sel_litmus_tests = litmus_tests if status else litmus_tests_fallback

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        now_str = now.strftime("%Y%m%d_%H%M%S_%f")

        self.benchmark_name_with_type = f"{self.benchmark_name}_{test_type}"
        self.benchmark_name_with_ts = f"{self.benchmark_name}_{test_type}_{now_str}"

        split_command = shlex.split(
            f". {gpu_source_script_path} {self.sel_vendor} {self.vulkan_sdk_version} && VK_DEVICE_ID={self.sel_device_id} \
            {test_exec_bin_path} \
            --file-config {sel_litmus_tests} \
            --benchmark-name '{self.benchmark_name_with_type}' \
            --test-repetitions {runtime_test_variables.get('test_repetitions', 10)} \
            --total-space {runtime_test_variables.get('total_space')} \
            --block-size {runtime_test_variables.get('block_size')} \
            --shuffle \
            --sg-size {runtime_test_variables.get('sg_size')} \
            --sg-stress-num {stress_sg_num} \
            --ignore-invalid-mapping \
            > >(tee /tmp/{self.benchmark_name_with_ts}.log) 2>&1"
        )

        run_command = split_command
        
        environment={
            "VK_DEVICE_ID" : self.sel_device_id,
        }

        wrapped_run_command, wrapped_environment = self._wrap_command(
            run_command=run_command,
            environment=environment,
            **kwargs
        )

        if self.is_dry_run:
            _cmd = " ".join(wrapped_run_command)
            self.curr_logger.info(f"[DRYRUN] {wrapped_environment} {_cmd}")
            remote_litmus_tests = self.platform.comm.shell(
                command=shlex.split(f"cat {litmus_tests}"),
                shell=True,
                print_input=False,
                print_output=True,
                output_is_log=True,
            )
            print(f"Number of litmus tests to run: {len(remote_litmus_tests)}")
            print(remote_litmus_tests)
            exit()
            return ""
        
        return self.run_bench_command(
            run_command=run_command,
            wrapped_run_command=wrapped_run_command,
            current_dir=current_dir,
            environment=environment,
            wrapped_environment=wrapped_environment,
            print_input=True,
            print_output=False,
            ignore_ret_codes=(1,100),
            ignore_any_error_code=True,
            shell=True,
        )

    def parse_output_to_results(  # pylint: disable=arguments-differ
        self,
        command_output: str,
        run_variables: Dict[str, Any],
        **_kwargs,
    ) -> Dict[str, Any]:

        print("Variables")
        print(run_variables)

        export_is_done = False
        str_content = ""
        if os.path.exists(gpu_verification_script):
            try:
                module_name = f"spirv_bm_module_{self.benchmark_name_with_ts}" # unique name
                spec = importlib.util.spec_from_file_location(module_name, gpu_verification_script)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                str_content = module.benchkit_generate_output(command_output)    
                export_is_done = True  
            except Exception as e:
                print(f"[ERROR] Something wrong while parsing: {e}")
                export_is_done = False
        
        result_dict = []
        if export_is_done:
        
            data={
                "headers" : str_content.splitlines()[0],
                "content" :  str_content.splitlines()[1:]
            }

            headers_list = data["headers"].split(';')
            content_lists = [d.split(';') for d in data["content"]]
            
            for content_list in content_lists:
                has_common_len = len(headers_list) == len(content_list)
                # common_len = min(len(headers_list), len(content_list))
                if has_common_len:
                    result_dict.append(dict(zip(headers_list, content_list)))
                    # result_dict.append(dict(zip(headers_list[:common_len], content_list[:common_len])))

        return result_dict