# hammertime: A high-volume http fetch library
# Copyright (C) 2016-  Delve Labs inc.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.


from asyncio import Future
from asyncio.queues import Queue
from collections import deque


class RequestScheduler:

    def __init__(self, requests=None, *, loop, limit=1000):
        self.done = Queue(loop=loop)
        self.loop = loop
        self.wait_queue = deque()
        self.pending_requests = []
        self.max_simultaneous_requests = limit

        for r in requests or []:
            self.request(r, schedule=False)
        self.schedule_max_possible_requests()

    def request(self, request, *, schedule=True):
        f = Future(loop=self.loop)
        self.wait_queue.append((request, f))
        if schedule:
            self.schedule_max_possible_requests()
        return f

    def schedule_max_possible_requests(self):
        while len(self.pending_requests) < self.max_simultaneous_requests:
            try:
                request, future = self.wait_queue.popleft()
                if not future.done():
                    self.schedule_request(request, future)
            except IndexError:
                return

    def schedule_request(self, request, future=None):
        task = self.loop.create_task(request)
        task.add_done_callback(self.on_completion)
        self.pending_requests.append(task)

        if future:
            task.add_done_callback(self._update_future(future))
            future.add_done_callback(self._cancel_sub(task))

    def on_completion(self, task):
        self.pending_requests.remove(task)
        self.schedule_max_possible_requests()

    def _update_future(self, future):
        def complete(task):
            if task.cancelled():
                future.cancel()
            else:
                exc = task.exception()
                if exc:
                    future.set_exception(exc)
                else:
                    future.set_result(task.result())
    
        return complete

    def _cancel_sub(self, task):
        def complete(future):
            if not task.done():
                if future.cancelled():
                    task.cancel()

        return complete

    async def __aiter__(self):
        return self

    async def __anext__(self):
        while not self.done.empty() or len(self.pending_requests) > 0 or len(self.wait_queue) > 0:
            return await self.done.get()
        raise StopAsyncIteration()