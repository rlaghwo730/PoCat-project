if __name__ == "__main__":
    import runpy
    runpy.run_module("tools.check_external_docs", run_name="__main__")
else:
    from tools.check_external_docs import *  # noqa: F401,F403
