import copy
import json
import math
from pathlib import Path
import tempfile
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4
from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from apps.api.weather_store import WeatherStore, validate_config, DEFAULT
from apps.api.weather_source import forecast, condition, validate_document, WeatherFailure, iso, SameOriginRedirect

NOW = 1793323800.0
POINT = dict(sceneId=str(uuid4()), label='Public example', latitude=39.9, longitude=116.4)


def document(start=NOW - 1800, updated=NOW - 3600):
    return dict(type='Feature', geometry=dict(type='Point', coordinates=[116.4, 39.9, 50]), properties=dict(
        meta=dict(updated_at=iso(updated), units=dict(air_temperature='celsius', wind_speed='m/s',
            wind_from_direction='degrees', cloud_area_fraction='%', precipitation_amount='mm')),
        timeseries=[dict(time=iso(start), data=dict(instant=dict(details=dict(air_temperature=18, wind_speed=3,
            wind_from_direction=45, cloud_area_fraction=80)), next_1_hours=dict(summary=dict(symbol_code='lightrain'), details=dict(precipitation_amount=.4))))]))


class WeatherSourceTests(unittest.TestCase):
    def test_period_units_and_forecast_identity(self):
        row=forecast(document(),NOW)
        self.assertTrue(row['usable']);self.assertEqual(row['condition'],'rain')
        self.assertEqual(row['windSpeedMs'],3);self.assertEqual(row['intervalHours'],1)
        self.assertEqual(row['validTo'],iso(NOW+1800))

    def test_expired_future_issue_and_no_period_are_not_usable(self):
        self.assertFalse(forecast(document(start=NOW-7200),NOW)['usable'])
        self.assertFalse(forecast(document(updated=NOW+3600),NOW)['usable'])
        self.assertFalse(forecast(document(updated=NOW-45000),NOW)['usable'])
        self.assertIsNone(forecast(document(start=NOW+1),NOW))
        d=document();del d['properties']['timeseries'][0]['data']['next_1_hours']
        self.assertIsNone(forecast(d,NOW))

    def test_missing_or_wrong_units_and_nonfinite_are_unknown_not_zero(self):
        d=document();d['properties']['meta']['units']['wind_speed']='km/h'
        d['properties']['timeseries'][0]['data']['instant']['details']['air_temperature']=math.nan
        row=forecast(d,NOW);self.assertIsNone(row['windSpeedMs']);self.assertIsNone(row['temperatureC'])

    def test_period_selection_and_missing_unknown_symbol(self):
        d=document();data=d['properties']['timeseries'][0]['data'];data['next_6_hours']=data.pop('next_1_hours')
        self.assertEqual(forecast(d,NOW)['intervalHours'],6)
        data['next_6_hours']['summary']['symbol_code']='unknown_rain'
        self.assertFalse(forecast(d,NOW)['usable'])
        for symbol,kind in [('clearsky_day','clear'),('heavysnowshowersandthunder_night','snow'),('lightsleet','sleet'),('fog','fog'),('partlycloudy','cloud'),('unexpected','unknown')]:self.assertEqual(condition(symbol),kind)

    def test_wrong_location_duplicates_or_oversize_steps_refused(self):
        validate_document(document(),POINT)
        for mutate in [lambda d:d['geometry'].update(coordinates=[0,0,0]),lambda d:d['properties']['timeseries'].extend(d['properties']['timeseries'])]:
            d=document();mutate(d)
            with self.assertRaises(WeatherFailure):validate_document(d,POINT)

    def test_cross_origin_redirect_never_forwards_contact(self):
        for url in ['http://api.met.no/weatherapi/x','https://127.0.0.1/','https://api.met.no@evil.test/','https://api.met.no/other']:
            with self.assertRaises(WeatherFailure):SameOriginRedirect().redirect_request(None,None,302,'',{},url)


class WeatherStoreTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.library=ModelLibrary(Path(temp.name)/'library','P',None)
        self.now=NOW;self.calls=[];self.result=(200,document(),{'last-modified':'Fri, 30 Oct 2026 00:00:00 GMT'})
        def fetch(*args):
            self.calls.append(args)
            if isinstance(self.result,Exception):raise self.result
            return self.result
        self.store=WeatherStore(self.library,'source',clock=lambda:self.now,fetcher=fetch)
        self.config={**DEFAULT,'enabled':True,'points':[POINT]}
    def body(self,revision=0):return dict(config=self.config,requestId=str(uuid4()),expectedRevision=revision)
    def test_config_isolated_cas_idempotency_and_actor(self):
        body=self.body();first=self.store.save('P','admin',body,lambda:None)
        self.assertEqual(first,self.store.save('P','admin',body,lambda:None));self.assertEqual(first['revision'],1)
        self.assertEqual(self.store.config('Q')['revision'],0)
        for other in [self.body(),{**body,'config':{**self.config,'enabled':False}}]:
            with self.assertRaises(PreviewError):self.store.save('P','admin',other,lambda:None)
    def test_denial_rolls_back_config(self):
        count=[0]
        def guard():
            count[0]+=1
            if count[0]>2:raise PreviewError(403,'FORBIDDEN')
        with self.assertRaises(PreviewError):self.store.save('P','admin',self.body(),guard)
        self.assertEqual(self.store.config('P')['revision'],0)
    def test_validation_rejects_bad_coordinates_contact_endpoint_and_duplicates(self):
        for bad in [math.nan,math.inf,True,91,'39.9']:
            with self.assertRaises(PreviewError):validate_config({**self.config,'points':[{**POINT,'latitude':bad}]})
        for change in [dict(endpoint='http://localhost'),dict(contact='x\r\nInjected:1'),dict(points=[POINT,POINT]),dict(refreshMinutes=1),dict(points=[])]:
            with self.assertRaises(PreviewError):validate_config({**self.config,**change})
        self.assertEqual(validate_config({**self.config,'points':[{**POINT,'latitude':-1.234567}]})['points'][0]['latitude'],-1.2345)
    def test_same_location_cache_is_shared_and_survives_new_runtime(self):
        first=self.store.current(self.config,POINT,lambda:None)
        self.assertEqual(first['status'],'available')
        self.now+=10
        self.store.current(self.config,{**POINT,'sceneId':str(uuid4())},lambda:None)
        self.assertEqual(len(self.calls),1)
        other=WeatherStore(self.library,'source',clock=lambda:self.now,fetcher=lambda *_:self.fail('unexpected external read'))
        self.assertEqual(other.current(self.config,POINT,lambda:None)['status'],'available')
    def test_expiry_and_conditional_read_use_provider_cache(self):
        self.result=(200,document(),{'expires':'Fri, 30 Oct 2026 12:00:00 GMT','last-modified':'Fri, 30 Oct 2026 00:00:00 GMT'})
        self.store.current(self.config,POINT,lambda:None);self.now+=10801
        self.store.current(self.config,POINT,lambda:None);self.assertEqual(len(self.calls),1)
        self.now+=86400;self.result=(304,None,{})
        value=self.store.current(self.config,POINT,lambda:None)
        self.assertEqual(self.calls[-1][2],'Fri, 30 Oct 2026 00:00:00 GMT');self.assertEqual(value['status'],'stale')
    def test_failure_retains_explicit_old_forecast_without_effects_or_repeated_calls(self):
        self.store.current(self.config,POINT,lambda:None);self.now+=10801
        self.result=WeatherFailure('WEATHER_RATE_LIMITED',1800)
        value=self.store.current(self.config,POINT,lambda:None)
        self.assertEqual(value['status'],'stale');self.assertEqual(value['error'],'WEATHER_RATE_LIMITED')
        self.now+=20;self.store.current(self.config,POINT,lambda:None);self.assertEqual(len(self.calls),2)
    def test_denial_after_network_discards_cache(self):
        count=[0]
        def guard():
            count[0]+=1
            if count[0]>1:raise PreviewError(403,'FORBIDDEN')
        with self.assertRaises(PreviewError):self.store.current(self.config,POINT,guard)
        with self.library.connect() as db:self.assertEqual(db.execute('select count(*) from weather_cache').fetchone()[0],0)
    def test_backup_library_copy_preserves_config_and_cache(self):
        self.store.save('P','admin',self.body(),lambda:None);self.store.current(self.config,POINT,lambda:None)
        target=self.library.root.parent/'restored'
        shutil.copytree(self.library.root,target)
        restored=WeatherStore(ModelLibrary(target,'P',None),'source',clock=lambda:self.now,fetcher=lambda *_:self.fail('unexpected fetch'))
        self.assertEqual(restored.config('P'),self.store.config('P'))
        self.assertEqual(restored.current(self.config,POINT,lambda:None)['status'],'available')
        self.assertEqual(restored.save('P','admin',self.body(1),lambda:None)['revision'],2)


if __name__=='__main__':unittest.main()
