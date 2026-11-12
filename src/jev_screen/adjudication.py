def adjudication_queue(reviewers,minimum_reviewers=2):
 error='Relectures invalides / Invalid reviews / Revisiones inválidas'
 if not isinstance(reviewers,dict)or not reviewers or len(reviewers)>100 or type(minimum_reviewers)is not int or not 2<=minimum_reviewers<=100:raise ValueError(error)
 identifiers=set()
 for name,labels in reviewers.items():
  if not isinstance(name,str)or not name or not isinstance(labels,dict):raise ValueError(error)
  for key,value in labels.items():
   if not isinstance(key,str)or not key or value is not None and type(value)is not bool:raise ValueError(error)
   identifiers.add(key)
 if len(identifiers)>100000:raise ValueError(error)
 rows=[]
 for key in sorted(identifiers):
  votes={name:labels[key]for name,labels in reviewers.items()if key in labels and labels[key]is not None};values=list(votes.values());conflict=len(set(values))>1;complete=len(values)>=minimum_reviewers
  rows.append({'id':key,'votes':votes,'reviewers_with_labels':len(values),'conflict':conflict,'consensus':values[0]if complete and not conflict else None,'needs_adjudication':conflict,'needs_more_reviews':not complete})
 return {'rows':rows,'majority_vote_applied':False,'provider_calls':0}
