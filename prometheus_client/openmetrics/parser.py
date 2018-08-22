#!/usr/bin/python

from __future__ import unicode_literals

try:
    import StringIO
except ImportError:
    # Python 3
    import io as StringIO

from .. import core


def text_string_to_metric_families(text):
    """Parse Openmetrics text format from a unicode string.

    See text_fd_to_metric_families.
    """
    for metric_family in text_fd_to_metric_families(StringIO.StringIO(text)):
        yield metric_family


def _unescape_help(text):
    result = []
    slash = False

    for char in text:
        if slash:
            if char == '\\':
                result.append('\\')
            elif char == '"':
                result.append('"')
            elif char == 'n':
                result.append('\n')
            else:
                result.append('\\' + char)
            slash = False
        else:
            if char == '\\':
                slash = True
            else:
                result.append(char)

    if slash:
        result.append('\\')

    return ''.join(result)


def _parse_sample(text):
    name = []
    labelname = []
    labelvalue = []
    value = []
    labels = {}

    state = 'name'

    for char in text:
        if state == 'name':
            if char == '{':
                state = 'startoflabelname'
            elif char == ' ':
                state = 'value'
            else:
                name.append(char)
        elif state == 'startoflabelname':
            if char == '}':
                state = 'endoflabels'
            else:
                state = 'labelname'
                labelname.append(char)
        elif state == 'labelname':
            if char == '=':
                state = 'labelvaluequote'
            else:
                labelname.append(char)
        elif state == 'labelvaluequote':
            if char == '"':
                state = 'labelvalue'
            else:
                raise ValueError("Invalid line: " + text)
        elif state == 'labelvalue':
            if char == '\\':
                state = 'labelvalueslash'
            elif char == '"':
                labels[''.join(labelname)] = ''.join(labelvalue)
                labelname = []
                labelvalue = []
                state = 'endoflabelvalue'
            else:
                labelvalue.append(char)
        elif state == 'endoflabelvalue':
            if char == ',':
                state = 'labelname'
            elif char == '}':
                state = 'endoflabels'
            else:
                raise ValueError("Invalid line: " + text)
        elif state == 'labelvalueslash':
            state = 'labelvalue'
            if char == '\\':
                labelvalue.append('\\')
            elif char == 'n':
                labelvalue.append('\n')
            elif char == '"':
                labelvalue.append('"')
            else:
                labelvalue.append('\\' + char)
        elif state == 'endoflabels':
            if char == ' ':
                state = 'value'
            else:
                raise ValueError("Invalid line: " + text)
        elif state == 'value':
            if char == ' ' or char == '#':
                # Timestamps and examplars are not supported, halt
                break
            else:
                value.append(char)
    if not value:
        raise ValueError("Invalid line: " + text)

    return core.Sample(''.join(name), labels, float(''.join(value)))
    

def text_fd_to_metric_families(fd):
    """Parse Prometheus text format from a file descriptor.

    This is a laxer parser than the main Go parser,
    so successful parsing does not imply that the parsed
    text meets the specification.

    Yields core.Metric's.
    """
    name = ''
    documentation = ''
    typ = 'untyped'
    unit = ''
    samples = []
    allowed_names = []
    eof = False

    def build_metric(name, documentation, typ, unit, samples):
        metric = core.Metric(name, documentation, typ, unit)
        # TODO: chheck only hitogram buckets have exemplars.
        # TODO: check samples are appropriately grouped and ordered
        # TODO: check metrics appear only once
        metric.samples = samples
        return metric

    for line in fd:
        if line[-1] == '\n':
          line = line[:-1]

        if eof:
            raise ValueError("Received line after # EOF: " + line)

        if line == '# EOF':
            eof = True
        elif line.startswith('#'):
            parts = line.split(' ', 3)
            if len(parts) < 2:
                raise ValueError("Invalid line: " + line)
            if parts[1] == 'HELP':
                if parts[2] != name:
                    if name != '':
                        yield build_metric(name, documentation, typ, unit, samples)
                    # New metric
                    name = parts[2]
                    unit = ''
                    typ = 'untyped'
                    samples = []
                    allowed_names = [parts[2]]
                if len(parts) == 4:
                    documentation = _unescape_help(parts[3])
                elif len(parts) == 3:
                    raise ValueError("Invalid line: " + line)
            elif parts[1] == 'TYPE':
                if parts[2] != name:
                    if name != '':
                        yield build_metric(name, documentation, typ, unit, samples)
                    # New metric
                    name = parts[2]
                    documentation = ''
                    unit = ''
                    samples = []
                typ = parts[3]
                allowed_names = {
                    'counter': ['_total', '_created'],
                    'summary': ['_count', '_sum', '', '_created'],
                    'histogram': ['_count', '_sum', '_bucket', 'created'],
                    'gaugehistogram': ['_bucket'],
                }.get(typ, [''])
                allowed_names = [name + n for n in allowed_names]
            else:
                raise ValueError("Invalid line: " + line)
        else:
            sample = _parse_sample(line)
            if sample[0] not in allowed_names:
                if name != '':
                    yield build_metric(name, documentation, typ, unit, samples)
                # Start an untyped metric.
                name = sample[0]
                documentation = ''
                unit = ''
                typ = 'untyped'
                samples = [sample]
                allowed_names = [sample[0]]
            else:
                samples.append(sample)

    if name != '':
        yield build_metric(name, documentation, typ, unit, samples)

    if not eof:
        raise ValueError("Missing # EOF at end")
