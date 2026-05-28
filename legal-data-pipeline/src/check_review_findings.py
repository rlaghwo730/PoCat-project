if __name__ == "__main__":
    import runpy
    runpy.run_module("tools.check_review_findings", run_name="__main__")
else:
    from tools.check_review_findings import *  # noqa: F401,F403
