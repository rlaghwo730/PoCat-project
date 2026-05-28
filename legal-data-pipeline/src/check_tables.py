if __name__ == "__main__":
    import runpy
    runpy.run_module("tools.check_tables", run_name="__main__")
else:
    from tools.check_tables import *  # noqa: F401,F403
