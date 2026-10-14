"""Deterministic OPC package construction. See NATIVE_NOTICE.md."""
import posixpath
import zipfile
from native_common import NS, NativeExportError, node, xml


def opc_xml(root, namespace):
    # LibreOffice's package detector requires the conventional default namespace
    # here, even though prefixed OPC elements are namespace-equivalent XML.
    for element in root.iter():
        element.tag = element.tag.removeprefix('{' + namespace + '}')
    root.set('xmlns', namespace)
    return xml(root)


class Package:
    def __init__(self):
        self.parts = {}
        self.types = {}
        self.relationships = {}

    def add(self, name, data, content_type):
        if name in self.parts:
            raise NativeExportError(f'duplicate package part: {name}')
        self.parts[name] = data if isinstance(data, bytes) else xml(data)
        self.types[name] = content_type

    def relate(self, owner, target, kind, external=False):
        entries = self.relationships.setdefault(owner, [])
        entry = (target, kind, external)
        if entry not in entries:
            entries.append(entry)
        return 'rId' + str(entries.index(entry) + 1)

    def write(self, destination):
        parts = dict(self.parts)
        for owner, entries in self.relationships.items():
            root = node('rel:Relationships')
            for i, (target, kind, external) in enumerate(entries, 1):
                if not external:
                    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(owner), target))
                    if resolved not in parts:
                        raise NativeExportError(f'dangling relationship: {owner} -> {target}')
                attrs = dict(Id=f'rId{i}', Type=kind if kind.startswith('http:') else NS['r'] + '/' + kind, Target=target)
                if external:
                    attrs['TargetMode'] = 'External'
                node('rel:Relationship', root, **attrs)
            name = (posixpath.dirname(owner) + '/_rels/' + posixpath.basename(owner) + '.rels').lstrip('/')
            parts[name] = opc_xml(root, NS['rel'])
        types = node('ct:Types')
        node('ct:Default', types, Extension='rels', ContentType='application/vnd.openxmlformats-package.relationships+xml')
        for name in sorted(self.parts):
            node('ct:Override', types, PartName='/' + name, ContentType=self.types[name])
        parts['[Content_Types].xml'] = opc_xml(types, NS['ct'])
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(parts):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, parts[name])
