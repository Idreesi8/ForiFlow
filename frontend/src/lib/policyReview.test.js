import assert from 'node:assert/strict';
import test from 'node:test';
import { checkedPolicyVersions, illustratedRecommendation, policyDraftFrom, policyReviewBlock, preparePolicyDraft } from './policyReview.js';

const active = { id: 1, version: '1.1', name: 'Synthetic policy', status: 'active', is_active: true, applications_assessed: 0,
  decline_max_score: 45, manual_review_max_score: 74, manager_approval_limit_pkr: 2_000_000, decline_override_admin_only: true };
const retired = { ...active, id: 2, version: '1.0', status: 'retired', is_active: false, decline_max_score: 40, manual_review_max_score: 70 };

test('new drafts copy active terms without reusing its immutable identity', () => {
  const form = policyDraftFrom(active);
  assert.equal(form.decline_max_score, '45'); assert.equal(form.manual_review_max_score, '74');
  assert.equal(form.version, ''); assert.equal(form.name, '');
  assert.equal(form.decline_override_admin_only, true);
  assert.throws(() => policyDraftFrom(null));
});
test('draft preparation trims, accepts zero limits and preserves decimal boundaries', () => {
  const form = { ...policyDraftFrom(active), version: ' 2.0 ', name: ' Synthetic new ', description: ' Purpose ', manager_approval_limit_pkr: '0', decline_max_score: '45.125' };
  assert.deepEqual(preparePolicyDraft(form), {version:'2.0', name:'Synthetic new', description:'Purpose', decline_max_score:45.125,
    manual_review_max_score:74, manager_approval_limit_pkr:0, decline_override_admin_only:true});
});
test('invalid or blank terms never silently become zero or enter a review', () => {
  const form = {...policyDraftFrom(active),version:'new',name:'Synthetic'};
  for (const change of [{decline_max_score:''},{decline_max_score:'NaN'},{manual_review_max_score:'Infinity'},
    {manager_approval_limit_pkr:'500000001'},{decline_max_score:'74'},{manual_review_max_score:'101'},
    {version:'bad space'},{version:'x'.repeat(33)},{name:'ab'},{description:'x'.repeat(2001)},{decline_override_admin_only:'false'}]) {
    assert.throws(() => preparePolicyDraft({...form,...change}), JSON.stringify(change));
  }
});
test('policy snapshots reject malformed, duplicated and contradictory active records', () => {
  assert.equal(checkedPolicyVersions([active,retired]).length,2);
  assert.throws(()=>checkedPolicyVersions([]),error=>error.code==='INVALID_POLICY_DETAILS');
  for (const rows of [null,[],[retired],[active,active],[active,{...retired,is_active:true}],[{...active,decline_max_score:'45'}],
    [{...active,manager_approval_limit_pkr:NaN}],[{...active,applications_assessed:1.5}],[active,{...retired,version:active.version}]]) assert.throws(() => checkedPolicyVersions(rows));
});
test('read-only comparisons are available to officers while writes require fresh admin authority', () => {
  const actor={username:'synthetic',role:'analyst'}, candidate={mode:'compare',policy:retired};
  assert.equal(policyReviewBlock(candidate,[active,retired],actor),null);
  assert.match(policyReviewBlock({...candidate,mode:'activate'},[active,retired],actor),/admin/);
  assert.match(policyReviewBlock(candidate,[active],actor),/no longer/);
  assert.match(policyReviewBlock(candidate,[active,retired],{}),/verified/);
});
test('activation and creation cannot blindly retry an already-completed transition', () => {
  const actor={username:'synthetic',role:'admin'};
  assert.match(policyReviewBlock({mode:'activate',policy:active},[active],actor),/already active/);
  assert.match(policyReviewBlock({mode:'create',policy:active},[active],actor),/already on file/);
  assert.equal(policyReviewBlock({mode:'activate',policy:retired},[active,retired],actor),null);
});
test('illustrations respect inclusive cut-offs and reject missing/out-of-range inputs', () => {
  for (const [score,label] of [['0','Decline'],['45','Decline'],['45.0001','Manual Review'],['74','Manual Review'],['74.0001','Approve'],['100','Approve']])
    assert.equal(illustratedRecommendation(score,active),'Recommend '+label);
  for (const score of ['', ' ', '-1','101','NaN','Infinity',null]) assert.equal(illustratedRecommendation(score,active),null);
  assert.equal(illustratedRecommendation('72',retired),'Recommend Approve');
  assert.equal(illustratedRecommendation('72',active),'Recommend Manual Review');
});
