if __name__ == "__main__":
    import runpy
    runpy.run_module("tools.check_active_sources", run_name="__main__")
else:
    from tools.check_active_sources import *  # noqa: F401,F403
