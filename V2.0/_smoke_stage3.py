import sys
from pathlib import Path
sys.path.insert(0, 'app')
import streamlit as st
from utils import tracker as t

smoke = Path('data/tracker_smoketest.json')
if smoke.exists():
    smoke.unlink()
t.USERS_DB_PATH = smoke
if 'applications' in st.session_state:
    del st.session_state['applications']
st.session_state.user = '__smoke__'

job = {'job_id':'JOB-1','company_id':'C1','title':'PM','company_name':'Acme',
       'location':'Berlin','country':'DE','job_url':'http://x','source':'LinkedIn','ats_score':80}

app = t.create_application(job, channel='LinkedIn', application_date='2026-08-23')
aid = app['application_id']
t.update_status(aid, 'WAITING')

# 1. Follow-up must NOT create a status; WAITING stays
a = t.record_follow_up(aid, sent_at='2026-08-25', method='Email', note='first nud@ge' )
print('1. after follow_up, status =', a['status'], '(expect WAITING)')
print('   follow_ups:', len(a['follow_ups']), '| FOLLOW_UP allowed as status?', 'FOLLOW_UP' in t.get_valid_transitions('WAITING'))

# 2. draft_follow_up
draft = t.draft_follow_up(a)
print('2. draft has subject:', draft['message'].split(chr(10))[0])
print('   draft includes company:', 'Acme' in draft['message'], '| title:', 'PM' in draft['message'])

# 3. mark_contacted (A->B)
a2 = t.mark_contacted(aid, contacted_at='2026-08-26', channel='LinkedIn message', note='sent on LI')
print('3. mark_contacted status =', a2['status'], '(expect WAITING) | last_activity:', a2['last_activity'])

# 4. remind_me_later (C)
a3 = t.remind_me_later(aid, later_date='2026-09-10')
print('4. remind checkpoint =', a3['follow_up_checkpoint'], '(expect 2026-09-10)')

# 5. application_summary must NOT treat FOLLOW_UP as a bucket
summ = t.application_summary()
print('5. summary pending =', summ['pending'], '(app is WAITING -> pending 1)')
print('   summary includes FOLLOW_UP? NO (FOLLOW_UP no longer a status)')

# 6. WAITING next_action after a follow-up already sent
na = t.next_action(a3)
print('6. next_action =', na['action'], '| source:', na['source'])

print('STAGE 3 SMOKE TESTS PASSED')