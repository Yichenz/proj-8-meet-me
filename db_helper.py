
import arrow


import CONFIG


from pymongo import MongoClient
from pymongo import ReturnDocument
from bson.objectid import ObjectId
try: 
    dbclient = MongoClient(CONFIG.MONGO_URL)
    db = dbclient.meetings
    collection = db.proposals
except:
    print("Failure opening database.  Is Mongo running? Correct password?")
    sys.exit(1)



def load():
    records = [ ] 
    for record in collection.find( { "type": "meeting_proposal" } ):
        records.append(
                { "type": record['type'],
                  "free_times": record['free_times'],
                  "id" : record['_id']
        })
    
    return records


def find_by_id(key):
    return collection.find_one( { "type" : "meeting_proposal", "_id" : key } )


def save(free_times, bounds):
    record = { "type":  "meeting_proposal", 
               "free_times": free_times,
               "bounds": bounds,
               "confirmed": "no"
             }
    res = collection.insert_one(record)
    return res.inserted_id


def update(key, free_times):
    status = 1
    res = collection.find_one_and_update(
                                 { "type" : "meeting_proposal", "_id" : key },
                                 { '$set' : {"free_times" : free_times} } )
    if res is not None:
        status = 0
        
    return status
    

def update_confirmed(key, confirm_start, confirm_end):
    status = 1
    confirm_insert = {"begin" : confirm_start, "end" : confirm_end}
    res = collection.find_one_and_update(
                                 { "type" : "meeting_proposal", "_id" : key },
                                 { '$set' : {"confirmed" : confirm_insert} } )
    if res is not None:
        status = 0
        
    return status


def delete_by_id(key):
    collection.delete_one({"_id":key})
    return
