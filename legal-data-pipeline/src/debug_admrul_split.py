if __name__ == "__main__":
    import runpy
    runpy.run_module("tools.debug_admrul_split", run_name="__main__")
else:
    from tools.debug_admrul_split import *  # noqa: F401,F403
