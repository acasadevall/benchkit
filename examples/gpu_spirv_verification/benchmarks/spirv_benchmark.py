# SPDX-License-Identifier: MIT

import git # TODO: replace with pythainer git + docker

from typing import Union  # For versions < 3.10
from benchmarks.utils.parser import my_parser
from benchmarks.utils import clean_up_ssh_connection

from benchkit.benchmark import Benchmark, CommandWrapper, CommandAttachment, SharedLib, PreRunHook, PostRunHook
from benchkit.platforms import Platform, get_current_platform, get_remote_platform
import pathlib
from benchkit.utils.dir import caller_dir

from typing import Any, Dict, List, Iterable

from benchkit.utils.types import Constants

import os, sys, shlex, re
import logging, functools
import datetime

_pylitmyus_repo_url = 'https://github.com/huawei-drc/gpu-verification.git'
_pylitmyus_repo_commit = 'dev'
_pylitmyus_repo_clone_name = 'pylitmus-benchkit'

_gpu_spirv_verification_repo_url = 'https://github.com/huawei-drc/gpu-verification.git'
_gpu_spirv_verification_repo_commit = "wg-sync-stress"
_gpu_spirv_verification_repo_clone_name = 'gpu-verification-benchkit'

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

    # @clean_up_ssh_connection
    @add_log()
    @staticmethod
    def get_platform_gpu_devices(platform: Platform) -> List[str]:
        if platform is None:
            return

        list_vk_devices = platform.comm.shell(
            command=shlex.split(f". ~/gpu.source && vulkaninfo --summary 2> /dev/null | grep GPU -A10 | grep -oE 'deviceName.*' | cut -d '=' -f 2"),
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

        out = platform.comm.shell(
            command=shlex.split(f"cd ~/pylitmus && git status"), # TODO: change to '~/pylitmus-benchkit' name
            shell=True,
            print_input=False,
            print_output=False,
            output_is_log=False,
            ignore_any_error_code=True
        )
        git_status &= False if "fatal" in out or "No such file or directory" in out else True

        return git_status

    @add_log()
    @staticmethod
    def do_git_preparation(platform: Platform, reset=False) -> bool:
        def _precheck_repo(repo_url: str, repo_clone_name: str, repo_commit: str, requires_submodule: bool = False) -> None:
            tmp_latest_repo = f"/tmp/{repo_clone_name}/latest"
            if VulkanPlatformUtils.do_git_repos_exist(platform=platform, repo_clone_name=repo_clone_name, repo_commit=repo_commit) and not reset:
                update_from_host = True
                try:
                    if pathlib.Path(tmp_latest_repo).is_dir():
                        repo = git.Repo(tmp_latest_repo)
                    else:
                        update_from_host = False    
                except git.exc.InvalidGitRepositoryError:
                    update_from_host = False
                    print(f"InvalidGitRepositoryError: {e}")
                except Exception as e:
                    update_from_host = False
                    print(f"ERROR: {e}")
                finally:
                    if update_from_host:
                        print(f"Update from Host: {repo_clone_name}/{repo_commit}")
                        repo.git.checkout(repo_commit)
                        if requires_submodule:
                            repo.submodule_update(init=True, recursive=True) # `git submodule update --init --recursive`
                        origin = repo.remotes.origin
                        origin.pull()  # `git pull`
                
                        platform.comm.copy_from_host(pathlib.Path(tmp_latest_repo).resolve(), "~/")

                        return
                    else:
                        # git clone and copy again
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

            platform.comm.copy_from_host(pathlib.Path(tmp_latest_repo).resolve(), "~/")
            print("Finish")
            return

        if platform is None:
            return
        
        # clean remote (possible) project
        if reset:
            print(f"Reset remote git: {_gpu_spirv_verification_repo_clone_name}/{_gpu_spirv_verification_repo_commit}")
            platform.comm.shell(
                command=shlex.split(f"rm -rf ~/{_gpu_spirv_verification_repo_clone_name} > /dev/null 2>&1"),
                shell=True,
                print_input=True,
                print_output=False,
                output_is_log=False,
                ignore_any_error_code=True,
            )
            # platform.comm.shell(
            #     command=shlex.split(f"rm -rf ~/{_pylitmyus_repo_clone_name} > /dev/null 2>&1"),
            #     shell=True,
            #     print_input=True,
            #     print_output=False,
            #     output_is_log=False,
            #     ignore_any_error_code=True,
            # )

        _precheck_repo(
            repo_url=_gpu_spirv_verification_repo_url,
            repo_clone_name=_gpu_spirv_verification_repo_clone_name,
            repo_commit=_gpu_spirv_verification_repo_commit,
            requires_submodule=True
        )
        # _precheck_repo(
        #     repo_url=_pylitmyus_repo_url,
        #     repo_clone_name=_pylitmyus_repo_clone_name,
        #     repo_commit=_pylitmyus_repo_commit
        # )

        return True
        
        # platform.comm.shell(
        #     command=shlex.split(f"cd ~/{_gpu_spirv_verification_repo_clone_name} && git submodule update --init --recursive"),
        #     shell=True,
        #     print_input=True,
        #     print_output=True,
        #     output_is_log=False,
        #     is_interactive=True,
        # )

        # platform.comm.shell(
        #     command=shlex.split(f"cd ~/ && git clone {_gpu_spirv_verification_repo_url} {_gpu_spirv_verification_repo_clone_name} && git checkout {_gpu_spirv_verification_repo_commit}"),
        #     shell=True,
        #     print_input=True,
        #     print_output=True,
        #     output_is_log=False,
        #     is_interactive=True,
        # )

        # platform.comm.shell(
        #     command=shlex.split(f"cd ~/ && git clone {_pylitmyus_repo_url} {_pylitmyus_repo_clone_name} && git checkout {_pylitmyus_repo_commit}"),
        #     shell=True,
        #     print_input=False,
        #     print_output=True,
        #     output_is_log=False,
        # )

    # @clean_up_ssh_connection
    @add_log()
    @staticmethod
    def get_platform_existing_tests(platform: Platform) -> List[str]:
        if platform is None:
            return []
        list_bin_tests = platform.comm.shell(
            command=shlex.split(f"find ~/{_gpu_spirv_verification_repo_clone_name}/examples/vulkan-cl-spirv-runtime/test/build/bin -type f 2> /dev/null | grep vk_spirv_runtime"),
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
    def prepare_platform_tests(platform: Platform, benchmark_name: str, device_id: int = 0, re_generate_is_needed: bool = True, is_dry_run: bool = False, filter_tests: List[str] = None) -> bool:
        if platform is None:
            return False
        
        out = ""
        n_retry = 5
        while n_retry >= 0 and not "updated" in out:
            out = platform.comm.shell(
                command=shlex.split(f"~/pylitmus/compilation/resources/kernels-dev/scripts/update_kernels.bash"),
                shell=True,
                print_input=False,
                print_output=False,
                output_is_log=False,            
            )
            n_retry-=1
        
        regex_tests = f"--regex \\\"(" + "|".join([re.escape(f_test) for f_test in filter_tests]) + ")\\\"" if filter_tests else ""
        skip_tests = 0 if re_generate_is_needed else 2 # skip tests via env variable
        dryrun_flag = "-n" if is_dry_run else ""
        
        command = shlex.split(
            f". ~/gpu.source && VK_DEVICE_ID={device_id} SKIP={skip_tests} ~/{_gpu_spirv_verification_repo_clone_name}/examples/vulkan-cl-spirv-runtime/test/scripts/benchmark.launch -tn \"{benchmark_name}\" -g \
            {regex_tests} \
            {dryrun_flag}"
        )

        # generate litmus tests for specific benchmark
        status = platform.comm.shell(
            command=command,
            shell=True,
            print_input=True,
            print_output=False,
            output_is_log=True,
        )
        
        return status != "" # TODO: we need status in comm shell ...

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

        self.ill_formed = False

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

        #TODO: add following stuff into PreHook
        # get Vulkan devices from platform and select from args: `device_info`
        list_vk_devices = VulkanPlatformUtils.get_platform_gpu_devices(platform=platform)
        if list_vk_devices is None or len(list_vk_devices) == 0:
            self.curr_logger.error(f"No Vulkan device in platform!")
            self.ill_formed = True
            return

        self.dict_platform_vk_devices = dict(zip(list(range(len(list_vk_devices))), list_vk_devices))

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

        device_found = False
        if device_name is not None:
            vk_device_names = [self.dict_platform_vk_devices[k] for k in self.dict_platform_vk_devices.keys()]
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
        else:
            self.curr_logger.info(f"DeviceID = {self.sel_device_id}, DeviceName = {self.sel_device_name}")

        platform_status = VulkanPlatformUtils.do_git_preparation(platform=platform, reset=False)
        if not platform_status:
            raise ValueError("Platform Git Error!")        

        #TODO: add following stuff into PreHook
        existing_tests = VulkanPlatformUtils.get_platform_existing_tests(platform=platform)
        valid_tests = []
        for t in existing_tests:
            m = re.search(r'vk_spirv_runtime_test_(.+)', t)
            if m:
                _t = m.group(1)
                trailings = ["_with_wg_sync","_with_wg_sync_debug","_debug"]
                for trailing in trailings:
                    if _t.endswith(trailing):
                        _t = _t[:-len(trailing)]
                        break
            valid_tests.append(_t)
        valid_tests = set(valid_tests)

        # set proper benchmark name based on platform/device name
        need_generate_test = True
        bm_name = " ".join(self.sel_device_name.strip().split()).replace(" ", "_").replace("(", "_").replace(")", "_")
        bm_name_2 = re.sub(r"[\[\]() ]", "_", " ".join(self.sel_device_name.strip().split()))
        assert bm_name == bm_name_2
        proposed_bm_name = f"benchkit_{bm_name}"

        if re_generate_always:
            # always generate, and create a new test if already exists (set SKIP=0)
            counter = 1
            while proposed_bm_name in valid_tests:
                proposed_bm_name = f"benchkit_{bm_name}_{counter}"
                counter += 1
        else:
            if proposed_bm_name in valid_tests:
                # skip generation in further commands (set SKIP=2)
                need_generate_test = False
            else:
                # test does not exists, we can proceed as usual with the new test
                # we must generate (set SKIP=0)
                pass

        VulkanPlatformUtils.prepare_platform_tests(platform=platform, device_id=self.sel_device_id, benchmark_name=proposed_bm_name, re_generate_is_needed=need_generate_test, is_dry_run=is_dry_run, filter_tests=litmus_tests)
        
        self.benchmark_name = proposed_bm_name
        self.litmus_tests = litmus_tests
        self.variables = variables
        self.is_dry_run = is_dry_run

        gl_record_variables = variables

    @property
    def bench_src_path(self) -> pathlib.Path:
        return caller_dir()

    @staticmethod
    def get_build_var_names() -> List[str]:
        return ["USE_VULKAN"]

    @staticmethod
    def get_run_var_names() -> List[str]:
        return gl_record_variables # this is a static method which cannot access self attributes ...
        # return [
        #     "litmus_test",
        #     "litmus_regex_tests",
        #     "block_size",
        #     "total_space",
        #     "test_repetitions",
        #     "with_device_loop",
        #     "random_gs",
        #     "shuffle",
        #     "shuffle_sg",
        #     "shuffle_wg",
        #     "wg_num",
        #     "sg_num",
        #     "sg_size",
        #     "sg_stress_num"
        # ]

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

    @clean_up_ssh_connection
    def single_run(
        self,
        # """ BEGIN my vars """
        # litmus_test: str,
        # litmus_regex_tests: str,
        # block_size: int,
        # total_space: int,
        # test_repetitions: int,
        # with_device_loop: bool,
        # random_gs: bool,
        # shuffle: bool,
        # shuffle_sg: bool,
        # shuffle_wg: bool,
        # wg_num: int,
        # sg_num: int,
        # sg_size: int,
        # sg_stress_num: int,
        # """ END my vars """
        constants: Constants = None,
        *args,
        **kwargs,
    ) -> str:
        runtime_test_variables = kwargs
        
        if len(runtime_test_variables) == 0:
            raise ValueError("No runtime test vars!")

        # self.platform.comm.copy_from_host(f"{src}/", f"{dst}/")

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        now_str = now.strftime("%Y%m%d_%H%M%S_%f")

        self.benchmark_name_with_ts = f"{self.benchmark_name}_{now_str}"
        
        current_dir="~/"
        
        bin_exe = f"vk_spirv_runtime_test_{self.benchmark_name}_with_wg_sync"
        bin_debug_exe = f"vk_spirv_runtime_test_{self.benchmark_name}_debug"
        bin_wg_sync_exe = f"vk_spirv_runtime_test_{self.benchmark_name}_with_wg_sync"
        bin_wg_sync_debug_exe = f"vk_spirv_runtime_test_{self.benchmark_name}_with_wg_sync_debug"

        regex_tests = f"--dis-regex \\\"(" + "|".join([re.escape(f_test) for f_test in self.litmus_tests]) + ")\\\"" if self.litmus_tests else ""

        test_exec_bin_path = pathlib.Path(f"~/{_gpu_spirv_verification_repo_clone_name}/examples/vulkan-cl-spirv-runtime/test/build/bin") / bin_wg_sync_exe
        
        shmem = ''
        glmem = ''
        if runtime_test_variables.get('sg_stress_num'):
            shmem = f"-shmem {runtime_test_variables.get('sg_num')*runtime_test_variables.get('sg_size') + 256}"
            glmem = f"-glmem 64"

        split_command = shlex.split(
            f". ~/gpu.source && VK_DEVICE_ID={self.sel_device_id} \
            {test_exec_bin_path} \
            --reporter automake \
            --test-repetitions {runtime_test_variables.get('test_repetitions', 10)} \
            --total-space {runtime_test_variables.get('total_space')} \
            --block-size {runtime_test_variables.get('block_size')} \
            --with-device-loop \
            --random-gs \
            --shuffle \
            {'--shuffle-wg' if runtime_test_variables.get('shuffle_wg') else ''} \
            {'--shuffle-sg' if runtime_test_variables.get('shuffle_sg') else ''} \
            --wg-num {runtime_test_variables.get('wg_num')} \
            --sg-num {runtime_test_variables.get('sg_num')} \
            --sg-size {runtime_test_variables.get('sg_size')} \
            --sg-stress-num {runtime_test_variables.get('sg_stress_num', 0)} \
            {glmem} \
            {shmem} \
            {regex_tests} \
            > >(tee -a ~/{self.benchmark_name_with_ts}.log) 2>&1"
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
            return ""
        
        return self.run_bench_command(
            run_command=run_command,
            wrapped_run_command=wrapped_run_command,
            current_dir=current_dir,
            environment=environment,
            wrapped_environment=wrapped_environment,
            print_output=False,
            ignore_ret_codes=(1,100),
            ignore_any_error_code=True,
            shell=True,
        )

    @staticmethod
    def _parse_results(data: Dict[str, str]) -> Dict[str, str]:
        
        minimum_key_data = [ "headers", "content"]

        if not isinstance(data, dict):
            raise ValueError(f"Invalid data. Must be a dictionary\n")

        if len(set(minimum_key_data) - set(data.keys())):
            raise ValueError(f"Invalid key data, please check data dictionary\n")

        headers = data["headers"] if "headers" in data else None
        content = data["content"] if "content" in data else None

        headers_list = data["headers"].split(';')
        content_lists = [d.split(';') for d in data["content"].split('\n')]
        
        result_dict = []
        for content_list in content_lists:
            common_len = min(len(headers_list), len(content_list))
            result_dict.append(dict(zip(headers_list[:common_len], content_list[:common_len])))

        print("result_dict")
        print(result_dict)

        return result_dict

    def parse_output_to_results(  # pylint: disable=arguments-differ
        self,
        command_output: str,
        run_variables: Dict[str, Any],
        **_kwargs,
    ) -> Dict[str, Any]:

        print("Variables")
        print(run_variables)

        headers, content = my_parser(command_output)
        
        return self._parse_results(data={ "headers" : headers, "content" : content })