if __name__ == "__main__":
    import runpy
    runpy.run_module("tools.check_inventory", run_name="__main__")
else:
    from tools.check_inventory import *  # noqa: F401,F403
