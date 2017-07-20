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


from time import time
from statistics import mean, stdev


class DynamicTimeout:

    def __init__(self, min_timeout, max_timeout, retries, sample_size=200):
        self.min_timeout = min_timeout
        self.max_timeout = max_timeout
        self.timeout_manager = TimeoutManager(min_timeout, max_timeout, sample_size)
        self.retries = retries
        self.request_engine = None

    def set_kb(self, kb):
        kb.timeout_manager = self.timeout_manager

    def set_engine(self, request_engine):
        self.request_engine = request_engine

    async def before_request(self, entry):
        if self._is_retry(entry):
            self.timeout_manager.add_failed_request(entry)
        if entry.result.attempt > self.retries:
            entry.arguments["timeout"] = self.max_timeout
        else:
            entry.arguments["timeout"] = self.timeout_manager.get_timeout()
        entry.arguments["start_time"] = time()
        self.request_engine.timeout = entry.arguments["timeout"]

    async def after_headers(self, entry):
        self.timeout_manager.add_successful_request(entry)

    def _is_retry(self, entry):
        return entry.result.attempt != 1


class TimeoutManager:

    def __init__(self, min_timeout, max_timeout, sample_size):
        self.min_timeout = min_timeout
        self.max_timeout = max_timeout
        self.request_delays = []
        self.samples_length = sample_size
        self.requests_successful = []
        self.last_retry_timeout = None

    def add_failed_request(self, entry):
        self.requests_successful.append(False)
        self.request_delays.append(entry.arguments["timeout"])
        if self.last_retry_timeout is not None:
            self.last_retry_timeout = max(entry.arguments["timeout"], self.last_retry_timeout)
        else:
            self.last_retry_timeout = entry.arguments["timeout"]

    def add_successful_request(self, entry):
        self.requests_successful.append(True)
        delay = time() - entry.arguments["start_time"]
        self.request_delays.append(delay)

    def get_timeout(self):
        if self.last_retry_timeout is not None and len(self.requests_successful) >= self.samples_length * 5:
            if all(self.requests_successful[-(self.samples_length * 5):]):
                self.last_retry_timeout = None
        if self.last_retry_timeout is not None:
            timeout = self.last_retry_timeout * 2
        elif len(self.request_delays) < self.samples_length:
            timeout = self.max_timeout * 0.8
        else:
            delays = self.request_delays[-self.samples_length:]
            timeout = mean(delays) * 2 + stdev(delays) * 4
        timeout = max(self.min_timeout, timeout)
        return min(timeout, self.max_timeout)