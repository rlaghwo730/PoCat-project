if __name__ == "__main__":
    import runpy
    runpy.run_module("tools.inspect_admrul_body", run_name="__main__")
else:
    from tools.inspect_admrul_body import *  # noqa: F401,F403
