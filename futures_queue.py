import asyncio
import logging

logger = logging.getLogger(__name__)

"""
Futures queue is a generic mechanism to get a Future promise for
data that will be delivered by an event in the future.
"""
class FuturesQueue:
    def __init__(self):
        self.__queue = dict()


    """
    Return a Future promise based on a key
    """
    def register(self, key: str):
        
        if key in self.__queue:
            logger.debug(f"returned existing future for {key}")
            return self.__queue[key]
        
        future = asyncio.shield(asyncio.Future())
        self.__queue[key] = future
        logger.debug(f"created new future for {key}")
        return asyncio.shield(future)
    
    def register_callback(self, key: str, func: callable):
        future = self.register(key)
        future.add_done_callback(func)

    """
    Process a result that may trigger a future promise that was
    previous requested.
    """
    def trigger(self, key: str, value):
        if key in self.__queue:
            logger.debug(f"triggered future for {key} with {value}")
            future = self.__queue[key]
            del self.__queue[key]
            future.set_result(value)
        else:
            logger.debug(f"triggered future for {key} with no listener")
        

    async def wait_for_data(self, key: str, timeout: int, default_value):
        try:
            if key in self.__queue:
                logger.debug(f"found future key in queue: {key}")
                future = self.__queue[key]
                logger.debug(f"waiting for future to complete: {key}")
                data = await asyncio.wait_for(future, timeout)
                logger.debug(f"future completed for key: {key}")
                return data
        except TimeoutError:
            logger.warning(f"timeout waiting for future: {key}")
            return default_value
        # except Exception as e:
        #     logger.warning(f"exception waiting for future: {e}")
        #     return default_value