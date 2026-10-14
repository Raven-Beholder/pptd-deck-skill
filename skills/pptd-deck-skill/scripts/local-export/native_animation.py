"""Compile click groups into PresentationML timing. See NATIVE_NOTICE.md.

Currently supports appear/disappear and fade entrance/exit, including delays and
the three trigger modes. Other effects are rejected instead of being downgraded.
"""
from dataclasses import dataclass
from native_common import NativeExportError, choice, fields, node, number, string


@dataclass(frozen=True)
class Event:
    shape_id: int
    effect: str
    trigger: str
    start: int
    duration: int


def schedule(animations, identifiers):
    if not isinstance(animations, list):
        raise NativeExportError('animations must be an array')
    groups = []
    previous = None
    for animation in animations:
        fields(animation, 'elementId effect trigger durationMs delayMs easing repeat', 'animation')
        identifier = string(animation.get('elementId'), 'animation.elementId')
        if identifier not in identifiers:
            raise NativeExportError(f'animation references missing element: {identifier}')
        effect = choice(animation.get('effect'), ('appear', 'disappear', 'fade-in', 'fade-out'), 'animation.effect')
        trigger = choice(animation.get('trigger', 'onClick'), ('onClick', 'withPrevious', 'afterPrevious'), 'animation.trigger')
        choice(animation.get('easing', 'linear'), ('linear',), 'animation.easing')
        if number(animation.get('repeat', 1), 'animation.repeat', 1) != 1:
            raise NativeExportError('animation repetition is not yet supported')
        duration = round(number(animation.get('durationMs', 500), 'animation.durationMs', 1, 86400000))
        if effect in ('appear', 'disappear'):
            duration = 1
        delay = round(number(animation.get('delayMs', 0), 'animation.delayMs', 0, 86400000))
        if not groups or trigger == 'onClick':
            groups.append((trigger == 'onClick', []))
            start = delay
        elif trigger == 'withPrevious':
            start = previous.start + delay
        else:
            start = previous.start + previous.duration + delay
        previous = Event(identifiers[identifier], effect, trigger, start, duration)
        groups[-1][1].append(previous)
    return groups


def timing(slide, animations, identifiers):
    groups = schedule(animations, identifiers)
    if not groups:
        return
    next_id = 0

    def time_node(parent, **attributes):
        nonlocal next_id
        next_id += 1
        return node('p:cTn', parent, id=next_id, **attributes)

    def condition(parent, delay):
        node('p:cond', node('p:stCondLst', parent), delay=delay)

    def behavior(parent, event, duration, attribute=None, delay=None):
        behavior = node('p:cBhvr', parent)
        time = time_node(behavior, dur=duration, fill='hold')
        if delay is not None:
            condition(time, delay)
        node('p:spTgt', node('p:tgtEl', behavior), spid=event.shape_id)
        if attribute:
            node('p:attrName', node('p:attrNameLst', behavior), text=attribute)

    def visibility(parent, event, visible, delay):
        setting = node('p:set', parent)
        behavior(setting, event, 1, 'style.visibility', delay)
        node('p:strVal', node('p:to', setting), val='visible' if visible else 'hidden')

    result = node('p:timing', slide)
    root = time_node(node('p:par', node('p:tnLst', result)), dur='indefinite', restart='never', nodeType='tmRoot')
    sequence = node('p:seq', node('p:childTnLst', root), concurrent='1', nextAc='seek')
    main = time_node(sequence, dur='indefinite', nodeType='mainSeq')
    timeline = node('p:childTnLst', main)
    builds = []
    for click, events in groups:
        group = time_node(node('p:par', timeline), fill='hold')
        condition(group, 'indefinite' if click else 0)
        children = node('p:childTnLst', group)
        for event in events:
            entrance = event.effect in ('appear', 'fade-in')
            group_id = len(builds)
            effect = time_node(node('p:par', children), presetID=10 if 'fade' in event.effect else 1,
                               presetClass='entr' if entrance else 'exit', presetSubtype=0,
                               dur=event.duration, fill='hold', grpId=group_id,
                               nodeType={'onClick': 'clickEffect', 'withPrevious': 'withEffect', 'afterPrevious': 'afterEffect'}[event.trigger])
            condition(effect, event.start)
            actions = node('p:childTnLst', effect)
            if entrance:
                visibility(actions, event, True, 0)
            if 'fade' in event.effect:
                behavior(node('p:animEffect', actions, transition='in' if entrance else 'out', filter='fade'), event, event.duration)
            if not entrance:
                visibility(actions, event, False, max(0, event.duration - 1))
            builds.append((event.shape_id, group_id))
    for tag, event in [('prevCondLst', 'onPrev'), ('nextCondLst', 'onNext')]:
        condition_node = node('p:cond', node('p:' + tag, sequence), evt=event, delay=0)
        node('p:sldTgt', node('p:tgtEl', condition_node))
    build_list = node('p:bldLst', result)
    for shape_id, group_id in builds:
        node('p:bldP', build_list, spid=shape_id, grpId=group_id, animBg='1')
