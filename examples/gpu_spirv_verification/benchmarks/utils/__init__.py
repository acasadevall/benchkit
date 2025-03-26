
import atexit, termios, sys, traceback
import signal
import functools
import shlex

class SttyException(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message
    
    def __str__(self):
        return f"Error: {self.message}"

def clean_up_ssh_connection(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        import shlex
        def handle_sigterm(signum, frame, platform, source=None):
            # kill residual processes
            print(f"kill_residual.sh {source}")
            killed = curr_platform.comm.shell(
                command=shlex.split(f"bash ~/gpu-verification-master/examples/vulkan-cl-spirv-runtime/test/scripts/kill_residual.sh"),
                shell=True,
                print_input=False,
                print_output=False,
                output_is_log=False,            
            )
        
        curr_platform = getattr(self, 'platform', None)

        if curr_platform:
            # register SIGTERM signal handler
            signal.signal(signal.SIGTERM, functools.partial(handle_sigterm, platform=curr_platform))
        
        ret = None
        try:
            ret = func(self, *args, **kwargs)
        except Exception as e:
            handle_sigterm(None, None, curr_platform, source="manual")
            raise SttyException(e)
        finally:
            return ret
    return wrapper
    
def reset_stty(func):
    """
    Decorator to wrap terminal reset after exiting program
    Example usage: 
    @reset_stty
    def main():
        ...
        pass
    get similar results as typing "stty sane" in terminal
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        def reset_terminal_settings(prev_settings):
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, prev_settings)
            except Exception as e:
                pass # ignore I/O operation on closed file when exit(0) or others
        
        # clean stty and terminal (similar to stty sane)
        prev_settings = termios.tcgetattr(sys.stdin)
        atexit.register(reset_terminal_settings, prev_settings)

        ret = None
        try:
            ret = func(*args, **kwargs)
        except SttyException as e:
            # manual call in case of other errors
            reset_terminal_settings(prev_settings)
            traceback.print_exc(file=sys.stderr)
            sys.exit(0)
        except Exception as e:
            reset_terminal_settings(prev_settings)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)
        finally:
            return ret

    return wrapper
