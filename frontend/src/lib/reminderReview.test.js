import test from 'node:test';
import assert from 'node:assert/strict';
import {filterReminders,readReminderFilters,reminderFilterQuery,reminderReturnState,validReminders,whatsappDraftURL} from './reminderReview.js';
const base={application_id:7,business_name:'Synthetic Hardware',applicant_name:'QA Officer',contact_phone:null,kind:'overdue',installment_number:2,installment_pkr:100.25,due_date:'2026-10-01',days_until_due:-28,arrears_pkr:0,latest_recorded_month:3,has_recording_gap:true,recorded_months_without_amount:1,message_en:'Synthetic English reminder.',message_ur:'Sirf test paigham.'};
test('accepts current reminder shapes and legitimate empty result',()=>{
  assert.equal(validReminders([base]),true);assert.equal(validReminders([]),true);
  assert.equal(validReminders([{...base,kind:'due_soon',days_until_due:0}]),true);
  assert.equal(validReminders([{...base,kind:'arrears',installment_number:null,due_date:null,days_until_due:null,arrears_pkr:12.34}]),true);
});
test('refuses duplicate, malformed and inconsistent current reminders',()=>{
  assert.equal(validReminders([base,base]),false);assert.equal(validReminders(null),false);
  for(const changes of [{application_id:'7'},{kind:'unknown'},{installment_pkr:Infinity},{arrears_pkr:-1},{due_date:'2026-02-30'},{days_until_due:2},{message_en:''},{has_recording_gap:'yes'},{recorded_months_without_amount:-1},{kind:'due_soon',days_until_due:8}])assert.equal(validReminders([{...base,...changes}]),false,JSON.stringify(changes));
});
test('search combines exact numeric case IDs with type and record filters',()=>{
  const other={...base,application_id:70,business_name:'Other shop',has_recording_gap:false,recorded_months_without_amount:0,contact_phone:'+923001234567'};
  assert.deepEqual(filterReminders([base,other],{search:'#7',kind:'overdue',coverage:'gap'}),[base]);
  assert.deepEqual(filterReminders([base,other],{search:' HARDWARE ',coverage:'unknown'}),[base]);
  assert.deepEqual(filterReminders([base,other],{coverage:'no_contact'}),[base]);
  assert.deepEqual(filterReminders([base],{kind:'arrears'}),[]);
});
test('restores safe URL filters without unknown values',()=>{
  assert.deepEqual(readReminderFilters(new URLSearchParams('kind=bad&coverage=bad')),{search:'',kind:'all',coverage:'all'});
  assert.equal(readReminderFilters(new URLSearchParams({search:'x'.repeat(150),kind:'arrears',coverage:'unknown'})).search.length,100);
});
test('WhatsApp draft uses only an international number and encoded message',()=>{
  const url=whatsappDraftURL('+923001234567','A & B?\nPKR 1,000.25');
  assert.equal(new URL(url).hostname,'wa.me');assert.equal(new URL(url).pathname,'/923001234567');
  assert.equal(new URL(url).searchParams.get('text'),'A & B?\nPKR 1,000.25');
  for(const phone of [null,'03001234567','../other?text=bad','+92300 1234567','+00000000','1234567890123456'])assert.equal(whatsappDraftURL(phone,'Test'),null);
});
test('return context preserves only safe reminder filters and cannot select an external route',()=>{
  const query=reminderFilterQuery({search:'A&B',kind:'overdue',coverage:'gap'});
  assert.equal(query,'search=A%26B&kind=overdue&coverage=gap');
  assert.deepEqual(reminderReturnState({reminderSearch:query}),{reminderSearch:query});
  assert.deepEqual(reminderReturnState({reminderSearch:'https://evil.example/path?search=stolen&coverage=unknown'}),{reminderSearch:'coverage=unknown'});
  assert.deepEqual(reminderReturnState({reminderSearch:''}),{reminderSearch:''});
  for(const input of [null,{}, {reminderSearch:123}, {reminderSearch:'x'.repeat(2001)}])assert.equal(reminderReturnState(input),null);
});
