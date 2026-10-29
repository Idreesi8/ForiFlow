import test from 'node:test';
import assert from 'node:assert/strict';
import { filterTeam, teamChangeBlock, roleLabel } from './teamAccess.js';
const users=[{id:1,username:'Idreesi',role:'admin',is_active:true},{id:2,username:'Branch.Manager',role:'manager',is_active:true},{id:3,username:'Former.Officer',role:'analyst',is_active:false}];
test('team search combines trimmed case-insensitive username, role and status filters',()=>{
  assert.deepEqual(filterTeam(users,{search:' BRANCH ',role:'manager',status:'enabled'}),[users[1]]);
  assert.deepEqual(filterTeam(users,{role:'analyst',status:'disabled'}),[users[2]]);
  assert.deepEqual(filterTeam(users,{search:'missing'}),[]);
  assert.deepEqual(filterTeam(users),users);
});
test('current authority and self changes block editing, while own history stays readable',()=>{
  assert.match(teamChangeBlock(users[1],users[1],'role'),/enabled admin/);
  assert.match(teamChangeBlock(users[0],users[0],'role'),/own role/);
  assert.match(teamChangeBlock(users[0],users[0],'status'),/own account/);
  assert.equal(teamChangeBlock(users[0],users[0],'history'),null);
  assert.equal(teamChangeBlock(users[1],users[0],'role'),null);
  assert.match(teamChangeBlock(null,users[0],'role'),/no longer/);
  assert.match(teamChangeBlock(users[1],{...users[0],is_active:false},'role'),/enabled admin/);
  assert.equal(roleLabel('manager'),'Manager');
});
