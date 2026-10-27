def parse_assignment(line):
    parts = line.split('=')
    return parts[0].strip(), parts[-1].strip()
