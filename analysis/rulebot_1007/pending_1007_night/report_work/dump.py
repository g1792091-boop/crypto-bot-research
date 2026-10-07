import json,sys
d=json.load(open(sys.argv[1]))
i=int(sys.argv[2])
L=d[i]
print('=== LENS',L['lens'])
for f in L['findings']:
    v=f.get('verification',{})
    print('\n##',f.get('id'),'[',f.get('confidence'),'] status=',v.get('status'))
    print('CLAIM:',f.get('claim'))
    print('EVID:',f.get('evidence'))
    print('IMPL:',f.get('implication'))
    print('RECOMP:',v.get('recomputed'))
    print('NOTE:',v.get('note'))
    extra=set(f.keys())-{'id','claim','evidence','confidence','implication','verification'}
    for k in extra: print(k.upper()+':',f[k])
print('\n-- strategy_note_problems'); [print('*',x if isinstance(x,str) else json.dumps(x,ensure_ascii=False)) for x in L.get('strategy_note_problems',[])]
print('\n-- verifier_missed'); [print('*',x if isinstance(x,str) else json.dumps(x,ensure_ascii=False)) for x in L.get('verifier_missed',[])]
print('\n-- limits'); [print('*',x if isinstance(x,str) else json.dumps(x,ensure_ascii=False)) for x in L.get('limits',[])]
