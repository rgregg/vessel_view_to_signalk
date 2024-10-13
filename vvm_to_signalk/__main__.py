"""Module for running the Vessel View to SignalK program"""

import asyncio
from .vvm_monitor import VesselViewMobileDataRecorder

if __name__ == "__main__":
    try:
        asyncio.run(VesselViewMobileDataRecorder().main())
    except RuntimeError:
        pass
