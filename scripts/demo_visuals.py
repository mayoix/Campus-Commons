"""Presentation snapshots for the isolated teaching scenarios (not live bookings)."""

def build_frames(key, scenario):
    mission_ids = {'conflict': ['M-101', 'M-102'], 'withdrawal': ['M-201', 'M-202'], 'replacement': ['M-301'], 'preference': ['M-401']}[key]
    names = {'conflict': ['Film Society', 'Design Club'], 'withdrawal': ['Music Club', 'Theatre Group'], 'replacement': ['Startup Lab'], 'preference': ['Robotics Team']}[key]
    resource_names = {'conflict': ['Camera A'], 'withdrawal': ['Rehearsal Room'], 'replacement': ['Studio A', 'Studio B'], 'preference': ['Lab A · P1', 'Lab B · P2']}[key]
    states = {
        'conflict': [[], ['Open'], ['Open', 'Open'], ['Frozen', 'Frozen'], ['Ranking', 'Ranking'], ['Allocated', 'Waitlisted']],
        'withdrawal': [['Open', 'Open'], ['Withdrawn', 'Open'], ['Withdrawn', 'Open'], ['Withdrawn', 'Frozen'], ['Withdrawn', 'Allocated']],
        'replacement': [['Allocated'], ['Booking released'], ['Replacement pending'], ['Awaiting confirmation'], ['Allocated']],
        'preference': [['Open'], ['Open'], ['Frozen'], ['Allocated']],
    }[key]
    frames = []
    for index, step in enumerate(scenario['timeline']):
        missions = [{'id': mission_ids[i], 'name': names[i], 'status': status} for i, status in enumerate(states[index])]
        resources = [{'name': name, 'status': 'Available', 'capacity': 1, 'booked_by': None} for name in resource_names]
        links = []
        show_scores = step['kind'] in ('decision', 'result') and key != 'replacement'
        if key == 'conflict':
            links = [{'mission': m['id'], 'resource': 0, 'status': 'requested'} for m in missions]
            if index == 4:
                resources[0]['status'] = 'Conflict: 2 requests / 1 slot'
            if index == 5:
                resources[0].update(status='Booked', booked_by='M-101')
                links = [{'mission': 'M-101', 'resource': 0, 'status': 'booked'}, {'mission': 'M-102', 'resource': 0, 'status': 'waitlisted'}]
        elif key == 'withdrawal':
            links = [{'mission': m['id'], 'resource': 0, 'status': 'withdrawn' if m['status'] == 'Withdrawn' else 'requested'} for m in missions]
            if index == 4:
                resources[0].update(status='Booked', booked_by='M-202')
                links[1]['status'] = 'booked'
        elif key == 'replacement':
            resources[0].update(status='Booked' if index == 0 else 'Unavailable · booking released', booked_by='M-301' if index == 0 else None)
            links = [{'mission': 'M-301', 'resource': 0, 'status': 'booked' if index == 0 else 'released'}]
            if index >= 2:
                links.append({'mission': 'M-301', 'resource': 1, 'status': 'booked' if index == 4 else 'proposed · not booked'})
            if index == 4:
                resources[1].update(status='Booked after confirmation', booked_by='M-301')
        else:
            if index >= 1:
                resources[0]['status'] = 'Occupied · infeasible'
            links = [{'mission': 'M-401', 'resource': 0, 'status': 'infeasible' if index >= 1 else '1st preference'}, {'mission': 'M-401', 'resource': 1, 'status': 'booked' if index == 3 else '2nd preference'}]
            if index == 3:
                resources[1].update(status='Booked', booked_by='M-401')
        frames.append({'missions': missions, 'resources': resources, 'links': links, 'show_scores': show_scores,
                       'rule': scenario['batch']['rule'], 'credit_delta': -5 if key == 'replacement' and index >= 1 else 0})
    return frames
