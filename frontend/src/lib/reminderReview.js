export const REMINDER_KINDS = {
  overdue: {label:'Overdue',className:'bg-rose-100 text-rose-800 ring-1 ring-rose-200'},
  arrears: {label:'Arrears',className:'bg-amber-100 text-amber-800 ring-1 ring-amber-200'},
  due_soon: {label:'Due soon',className:'bg-sky-100 text-sky-800 ring-1 ring-sky-200'},
};
const integer = (n,min=0) => Number.isSafeInteger(n)&&n>=min;
const amount = n => typeof n==='number'&&Number.isFinite(n)&&n>=0;
const date = value => {
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed=new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.valueOf())&&parsed.toISOString().slice(0,10)===value;
};
export function validReminders(rows) {
  return Array.isArray(rows)&&new Set(rows.map(row=>row?.application_id)).size===rows.length&&rows.every(row=>row&&
    integer(row.application_id,1)&&Object.hasOwn(REMINDER_KINDS,row.kind)&&
    ['business_name','applicant_name','message_en','message_ur'].every(key=>typeof row[key]==='string'&&row[key].trim())&&
    (row.contact_phone===null||typeof row.contact_phone==='string')&&amount(row.installment_pkr)&&row.installment_pkr>0&&amount(row.arrears_pkr)&&
    integer(row.latest_recorded_month)&&integer(row.recorded_months_without_amount)&&typeof row.has_recording_gap==='boolean'&&
    (row.kind==='arrears' ? row.installment_number===null&&row.due_date===null&&row.days_until_due===null&&row.arrears_pkr>0 :
      integer(row.installment_number,1)&&date(row.due_date)&&Number.isSafeInteger(row.days_until_due)&&
      (row.kind==='overdue'?row.days_until_due<0:row.days_until_due>=0&&row.days_until_due<=7)));
}
export function whatsappDraftURL(phone,message) {
  if(typeof phone!=='string'||!/^\+?[1-9]\d{6,14}$/.test(phone)||typeof message!=='string'||!message.trim())return null;
  return `https://wa.me/${phone.replace(/^\+/,'')}?text=${encodeURIComponent(message)}`;
}
export function filterReminders(rows,{search='',kind='all',coverage='all'}={}) {
  const query=search.trim().toLocaleLowerCase();
  const caseId=query.match(/^#?(\d+)$/)?.[1];
  return rows.filter(row=>(!query||(caseId?row.application_id===Number(caseId):`${row.business_name} ${row.applicant_name}`.toLocaleLowerCase().includes(query)))&&
    (kind==='all'||row.kind===kind)&&
    (coverage==='all'||(coverage==='gap'&&row.has_recording_gap)||(coverage==='unknown'&&row.recorded_months_without_amount>0)||
      (coverage==='no_contact'&&!whatsappDraftURL(row.contact_phone,row.message_en))));
}
export function readReminderFilters(params) {
  return {search:(params.get('search')??'').slice(0,100),
    kind:Object.hasOwn(REMINDER_KINDS,params.get('kind'))?params.get('kind'):'all',
    coverage:['gap','unknown','no_contact'].includes(params.get('coverage'))?params.get('coverage'):'all'};
}

export function reminderFilterQuery(filters) {
  const safe=readReminderFilters(new URLSearchParams(filters));
  const query=new URLSearchParams();
  for(const [key,value] of Object.entries(safe))if(value&&value!=='all')query.set(key,value);
  return query.toString();
}

export function reminderReturnState(state) {
  if(!state||!Object.hasOwn(state,'reminderSearch')||typeof state.reminderSearch!=='string'||state.reminderSearch.length>2000)return null;
  return {reminderSearch:reminderFilterQuery(readReminderFilters(new URLSearchParams(state.reminderSearch)))};
}
