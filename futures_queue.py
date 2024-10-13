"""Helpers for async processing"""
import asyncio
import logging

logger = logging.getLogger(__name__)
class FuturesQueue:
    """ Futures queue is a generic mechanism to get a Future promise for
        data that will be delivered by an event in the future.  """

    def __init__(self):
        self.__queue = {}

    def register(self, key: str):
        """Return a Future promise based on a key"""    

        if key in self.__queue:
            logger.debug("returned existing future for %s", key)
            return self.__queue[key]
        
        future = asyncio.shield(asyncio.Future())
        self.__queue[key] = future
        logger.debug("created new future for %s", key)
        return future
    
    def register_callback(self, key: str, func: callable):
        """Registers a future callback for a key"""
        future = self.register(key)
        future.add_done_callback(func)

    def trigger(self, key: str, value):
        """
        Process a result that may trigger a future promise that was
        previous requested.
        """

        if key in self.__queue:
            logger.debug("triggered future for %s with %s", key, value)
            future = self.__queue[key]
            del self.__queue[key]
            future.set_result(value)
        else:
            logger.warning("triggered future for %s with no listener", key)
        

    async def wait_for_data(self, key: str, timeout: int, default_value):
        """Waites for a key for a given timeout"""
        try:
            if key in self.__queue:
                logger.debug("found future key in queue: %s", key)
                future = self.__queue[key]
                logger.debug("waiting for future to complete: %s", key)
                data = await asyncio.wait_for(future, timeout)
                logger.debug("future completed for key: %s", key)
                return data
        except TimeoutError:
            logger.warning("timeout waiting for future: %s", key)
            return default_value
