import test from 'node:test';
import assert from 'node:assert/strict';
import { CASHFLOW_METHODS, matchesCashflowReport, statementFingerprint, syntheticCashflowCSV } from './cashflowIntelligence.js';

const series = Array.from({length:36}, (_,i) => ({month:`${2023+Math.floor(i/12)}-${String(i%12+1).padStart(2,'0')}`,inflow:100,outflow:50,transactions:2}));
const report = { method_version:'cashflow-local-v2', parser_version:'statement-v2',source_sha256:'a'.repeat(64),computed_at:'2026-10-28T10:00:00Z',as_of_date:'2026-10-28',
  source_quality:{method_version:'cashflow-import-v1',date_order_requested:'auto',date_order_resolved:'iso_or_named',ambiguous_numeric_rows:0,normalised_date_rows:0,source_rows:72,repeated_row_candidates:0,repeated_row_examples:[],parsed_source_sha256:'c'.repeat(64),notes:['No automatic deduplication']},
  observations:36,first_month:'2023-01',last_month:'2025-12',series,omitted_chart_months:0,trend_window_months:12,trend_slope_pkr_per_month:0,recent_three_vs_previous_three_percent:0,
  negative_net_months:0,unreadable_rows:0,quiet_months:[],warnings:[],notes:['Not a lending decision'],
  forecast:{status:'ready',selected_method:'last_month',candidates:CASHFLOW_METHODS.map(method=>({method,development_mae_pkr:0})),
    development_months:series.slice(-18,-12).map(row=>row.month),calibration_months:series.slice(-12,-6).map(row=>row.month),
    test_months:series.slice(-6).map(row=>({month:row.month,observed_pkr:100,predicted_pkr:100,baseline_pkr:100,lower_pkr:100,upper_pkr:100})),
    empirical_radius_pkr:0,test_mae_pkr:0,baseline_test_mae_pkr:0,test_months_inside_band:6,next_month:'2026-01',predicted_pkr:100,lower_pkr:100,upper_pkr:100} };

test('complete source-matched chronological results are accepted',()=>assert.equal(matchesCashflowReport(report,'a'.repeat(64)),true));
test('wrong sources and unsupported methods cannot show results',()=>{
  assert.equal(matchesCashflowReport(report,'b'.repeat(64)),false);
  for(const change of [r=>r.method_version='other',r=>r.forecast.selected_method='invented',r=>r.forecast.candidates.pop(),r=>r.forecast.candidates.reverse()]){
    const altered=structuredClone(report);change(altered);assert.equal(matchesCashflowReport(altered,'a'.repeat(64)),false);
  }
});
test('nonfinite and impossible values are withheld',()=>{
  for(const change of [r=>r.series[0].inflow=NaN,r=>r.trend_slope_pkr_per_month=Infinity,r=>r.forecast.lower_pkr=101,r=>r.forecast.test_mae_pkr=-1,r=>r.forecast.test_months_inside_band=7]){
    const altered=structuredClone(report);change(altered);assert.equal(matchesCashflowReport(altered,'a'.repeat(64)),false);
  }
});
test('chronological overlap and source-observation mismatches are withheld',()=>{
  for(const change of [r=>r.forecast.calibration_months=r.forecast.development_months,r=>r.forecast.next_month='2025-12',r=>r.forecast.test_months[0].observed_pkr=99,r=>r.series[1].month='2023-01']){
    const altered=structuredClone(report);change(altered);assert.equal(matchesCashflowReport(altered,'a'.repeat(64)),false);
  }
});
test('inconsistent displayed errors, coverage, ranges and selection are withheld',()=>{
  for(const change of [r=>r.forecast.test_mae_pkr=2,r=>r.forecast.test_months_inside_band=5,r=>r.forecast.upper_pkr=110,r=>r.forecast.selected_method='median_6']){
    const altered=structuredClone(report);change(altered);assert.equal(matchesCashflowReport(altered,'a'.repeat(64)),false);
  }
});
test('quality-blocked and insufficient histories explain why without inventing estimates',()=>{
  for(const status of ['quality_blocked','insufficient_history']) {
    const altered=structuredClone(report);altered.forecast={status,reason:'Explanation',required_months:30};
    assert.equal(matchesCashflowReport(altered,'a'.repeat(64)),true);
  }
  const altered=structuredClone(report);altered.quiet_months=['2024-01'];
  assert.equal(matchesCashflowReport(altered,'a'.repeat(64)),false);
});
test('fingerprints use exact decoded UTF-8 source contents',async()=>{
  assert.equal(await statementFingerprint('abc'),'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  assert.notEqual(await statementFingerprint('abc'),await statementFingerprint('abc\n'));
});
test('synthetic example is deterministic, has 36 populated months and no identity columns',()=>{
  const csv=syntheticCashflowCSV(); assert.equal(csv,syntheticCashflowCSV());
  assert.equal(csv.split('\n')[0],'date,type,amount');
  assert.equal(csv.trim().split('\n').length,109);
  assert.equal(new Set(csv.trim().split('\n').slice(1).map(row=>row.slice(0,7))).size,36);
  assert.ok(csv.trim().split('\n').slice(1).every(row=>/^\d+\.\d{2}$/.test(row.split(',')[2])));
});

test('source quality must match the selected date convention and contain valid evidence',()=>{
  assert.equal(matchesCashflowReport(report,'a'.repeat(64),'day_first'),false);
  for (const change of [r=>r.source_quality=null,r=>r.source_quality.date_order_requested='day_first',r=>r.source_quality.ambiguous_numeric_rows=73,r=>r.source_quality.parsed_source_sha256='bad',r=>r.source_quality.repeated_row_candidates=1]) {
    const altered=structuredClone(report);change(altered);assert.equal(matchesCashflowReport(altered,'a'.repeat(64)),false);
  }
  const altered=structuredClone(report);
  altered.source_quality={...altered.source_quality,date_order_requested:'day_first',date_order_resolved:'day_first',ambiguous_numeric_rows:20,repeated_row_candidates:1,repeated_row_examples:[{first_line:2,repeated_line:10}]};
  assert.equal(matchesCashflowReport(altered,'a'.repeat(64),'day_first'),true);
});
