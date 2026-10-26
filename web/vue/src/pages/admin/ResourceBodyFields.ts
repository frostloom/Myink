import { Fragment, h as renderNode } from 'vue';
import type { GenreFields } from "../../../../src/lib/genrePacks";
import { internalResourceFields, resourceFieldLabels } from "../../../../src/lib/resourceFieldLabels";
import type { ResourceBody, ResourceKind } from "../../../../src/lib/writingResources";
import AutoTextarea from "../../components/AutoTextarea.vue";
import GenrePackFields from "../../components/GenrePackFields.vue";
function Fields({ value, onChange, path, }: {
    value: unknown;
    onChange: (v: unknown) => void;
    path: string;
}) {
    if (internalResourceFields.has(path))
        return null;
    if (Array.isArray(value))
        return (renderNode("fieldset", {}, [
            renderNode("legend", {}, [resourceFieldLabels[path] ?? "创作内容"]), value.map((item, index: number) => (renderNode("div", { "key": index }, [
                renderNode(Fields, { "value": item, "path": typeof item === "string" ? `${resourceFieldLabels[path] ?? "条目"} ${index + 1}` : `文件 ${index + 1}`, "onChange": (next: unknown) => onChange(value.map((old, i: number) => (i === index ? next : old))) }), renderNode("button", { "class": "btn btn-quiet", "type": "button", "onClick": () => onChange(value.filter((_, i: number) => i !== index)) }, [
                    "移除第 ", index + 1, " 项"
                ])
            ]))), renderNode("button", { "class": "btn", "type": "button", "onClick": () => onChange([
                    ...value,
                    path === "files" ? { path: `reference-${crypto.randomUUID()}.md`, content: "" } : "",
                ]) }, [
                "添加", resourceFieldLabels[path] ?? "创作内容"
            ])
        ]));
    if (value && typeof value === 'object')
        return (renderNode("fieldset", {}, [
            renderNode("legend", {}, [resourceFieldLabels[path] ?? "创作内容"]), Object.entries(value).map(([key, item]) => (renderNode(Fields, { "key": key, "path": key, "value": item, "onChange": (next: unknown) => onChange({ ...value, [key]: next }) })))
        ]));
    const label = resourceFieldLabels[path] ?? (/[a-z_]/i.test(path) ? '创作要求' : path);
    if (typeof value === 'boolean')
        return (renderNode("label", { "style": { display: "block" } }, [
            renderNode("input", { "type": "checkbox", "checked": value, "onChange": (e: Event) => onChange((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).checked) }, []), label
        ]));
    if (typeof value === 'number')
        return (renderNode("label", { "style": { display: "block" } }, [
            label, renderNode("input", { "class": "input", "type": "number", "value": value, "onInput": (e: Event) => onChange(Number((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value)) }, [])
        ]));
    return (renderNode("label", { "style": { display: "block", marginBottom: "1rem" } }, [
        label, renderNode(AutoTextarea, { "class": "textarea", "rows": path === "content" ? 12 : 4, "value": String(value ?? ""), "onChange": (e: Event) => onChange((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) })
    ]));
}
export function ResourceBodyFields({ kind, value, onChange, genres = [], }: {
    genres?: {
        id: string;
        name: string;
    }[];
    kind: ResourceKind;
    value: ResourceBody;
    onChange: (v: ResourceBody) => void;
}) {
    if (kind === 'genre' && 'fields' in value)
        return (renderNode(Fragment, {}, [
            renderNode(GenrePackFields, { "value": value.fields as GenreFields, "onChange": (fields: GenreFields) => onChange({ ...value, fields }) }), value.setup_caps && (renderNode(Fields, { "path": "setup_caps", "value": value.setup_caps, "onChange": (setup_caps: unknown) => onChange({
                    ...value,
                    setup_caps: setup_caps as Record<string, unknown>,
                }) }))
        ]));
    return (renderNode(Fragment, {}, [
        kind === "genre_rule" && "roles" in value && (renderNode("fieldset", {}, [
            renderNode("legend", {}, ["适用题材"]), renderNode("p", {}, ["未选择时适用于所有题材。"]), genres.map((genre: {
                id: string;
                name: string;
            }) => renderNode("label", { "key": genre.id }, [
                renderNode("input", { "type": "checkbox", "checked": value.genre_ids?.includes(genre.id) ?? false, "onChange": (e: Event) => onChange({ ...value, genre_ids: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).checked ? [...(value.genre_ids ?? []), genre.id] : (value.genre_ids ?? []).filter((id: string) => id !== genre.id) }) }, []), genre.name
            ]))
        ])), renderNode(Fields, { "path": "资源内容", "value": value, "onChange": (next: unknown) => onChange(next as ResourceBody) })
    ]));
}
Fields.props = ["value", "onChange", "path"];
Fields.inheritAttrs = false;
ResourceBodyFields.props = ["kind", "value", "onChange", "genres"];
ResourceBodyFields.inheritAttrs = false;
