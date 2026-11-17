"""Short-lived, single-use delivery grants for existing fixed photo reads."""
from collections import OrderedDict
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
import re

from .authority import PreviewError


ANALYSIS_PHOTO = '/api/workbench/analysis-sessions/evidence/content'
ANALYSIS_BATCH = '/api/workbench/analysis-sessions/evidence/batch'
MEDIA_PATH = '/v1/fixed-photo'
PHOTO_ROUTES = {
    ANALYSIS_PHOTO: 'analysis_request',
    '/api/workbench/objects/photos/content': 'scene_object_request',
    '/api/workbench/equipment/materials/content': 'equipment_request',
    '/api/workbench/equipment/shared-photos/content': 'equipment_request',
    '/api/workbench/work-orders/attachments/content': 'work_order_request',
    '/api/workbench/work-orders/analysis-source': 'work_order_request',
}
PHOTO_HEADER = 'X-Vis-Photo-Read'
TICKET_BYTES = 43
TICKET_LIFETIME = 90
MAX_TICKETS = 2048


class PhotoTickets:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.lock = Lock()
        self.tickets = OrderedDict()

    def issue(self, sid, path, payload):
        if path not in PHOTO_ROUTES:
            raise ValueError('Ticket requires a fixed photo route')
        token = token_urlsafe(32)
        with self.lock:
            now = self.clock()
            while self.tickets and (len(self.tickets) >= MAX_TICKETS or next(iter(self.tickets.values()))[0] <= now):
                self.tickets.popitem(last=False)
            self.tickets[token] = (now + TICKET_LIFETIME, sid, path, payload)
        return token

    def consume(self, token):
        if not re.fullmatch(rb'[A-Za-z0-9_-]{43}', token):
            raise PreviewError(401, 'PHOTO_TICKET_REQUIRED')
        with self.lock:
            entry = self.tickets.pop(token.decode('ascii'), None)
        if entry is None or entry[0] <= self.clock():
            raise PreviewError(410, 'PHOTO_TICKET_EXPIRED')
        return entry[1:]
