from src.database.account.models import Availability
from datetime import time

from typing import List, Tuple

# def merge(li, e1, e2):
#     del li[e1.]

# #will take in an enumeration(all_availabilities), returns enum(...) with new indexes for merges, removes original indices 
# # all availabilities include incoming avail
# def merge_availability_timelines(avails: List[Tuple[int, Availability]]):
#     #windowing algorithm
#     a = sorted(avails, key=lambda x: x[1].start_time)

#     merged_agg = []

    

#     for idx in range(len(a) - 1):
#         if a[idx + 1][1].start_time < a[idx][1].end_time: #the current event ends AFTER the next one starts
#             pass #merge
        