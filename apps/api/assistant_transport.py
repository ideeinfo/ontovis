"""Cancelable, bounded loopback POST for the dedicated source assistant route."""
import http.client
import json
import socket
from threading import Event, Thread
import time
from urllib.parse import urlsplit
from .authority import PreviewError

def call_source(authority, path, body, cancelled, deadline):
    parsed=urlsplit(authority.base_url)
    if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not path.startswith('/api/v1/projects/') or not path.endswith('/ontovis-assistant/analyze'):
        raise PreviewError(422,'INVALID_REQUEST')
    connection=http.client.HTTPConnection(parsed.hostname,parsed.port,timeout=min(55,max(1,deadline-time.monotonic())))
    finished=Event()
    def watch():
        while not finished.wait(0.1):
            if cancelled.is_set() or time.monotonic()>=deadline:
                try:
                    if connection.sock:connection.sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
                connection.close();return
    watcher=Thread(target=watch,daemon=True);watcher.start()
    try:
        if cancelled.is_set():raise PreviewError(409,'ASSISTANT_CANCELLED')
        connection.request('POST',path,body=json.dumps(body).encode(),headers={
            'Authorization':'Bearer '+(authority.token or ''),'Content-Type':'application/json','Accept':'application/json'})
        response=connection.getresponse();raw=response.read(65537)
        if len(raw)>65536:raise PreviewError(502,'ASSISTANT_OUTPUT_INVALID')
        result=json.loads(raw)
        if type(result) is not dict:raise PreviewError(502,'ASSISTANT_OUTPUT_INVALID')
        if response.status!=200:
            code=(result.get('detail') or {}).get('code') if type(result.get('detail')) is dict else None
            raise PreviewError(response.status if response.status in (401,403,409,422,429,503) else 502,
                code if type(code) is str and code.startswith('ASSISTANT_') else 'ASSISTANT_MODEL_UNAVAILABLE')
        return result
    except PreviewError:raise
    except (OSError,ValueError,http.client.HTTPException):
        raise PreviewError(409 if cancelled.is_set() else 504 if time.monotonic()>=deadline else 502,
            'ASSISTANT_CANCELLED' if cancelled.is_set() else 'ASSISTANT_TIMEOUT' if time.monotonic()>=deadline else 'ASSISTANT_MODEL_UNAVAILABLE') from None
    finally:
        finished.set();connection.close();watcher.join(timeout=0.2)
