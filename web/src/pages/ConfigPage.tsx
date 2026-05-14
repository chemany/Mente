import { useEffect, useLayoutEffect, useRef, useState, useMemo } from "react";
import {
  Code,
  Download,
  FormInput,
  RotateCcw,
  Save,
  Search,
  Upload,
  X,
  Settings2,
  FileText,
  Settings,
  Bot,
  Monitor,
  Palette,
  Users,
  Brain,
  Package,
  Lock,
  Globe,
  Mic,
  Volume2,
  Ear,
  ClipboardList,
  MessageCircle,
  Wrench,
  FileQuestion,
  Filter,
  Plus,
  KeyRound,
} from "lucide-react";
import { api } from "@/lib/api";
import { getNestedValue, setNestedValue } from "@/lib/nested";
import { useToast } from "@/hooks/useToast";
import { Toast } from "@/components/Toast";
import { AutoField } from "@/components/AutoField";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectOption } from "@/components/ui/select";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { PluginSlot } from "@/plugins";
import type {
  ModelOptionsResponse,
  ModelProviderCreateRequest,
  ModelProviderOption,
} from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const CATEGORY_ICONS: Record<
  string,
  React.ComponentType<{ className?: string }>
> = {
  general: Settings,
  agent: Bot,
  terminal: Monitor,
  display: Palette,
  delegation: Users,
  memory: Brain,
  compression: Package,
  security: Lock,
  browser: Globe,
  voice: Mic,
  tts: Volume2,
  stt: Ear,
  logging: ClipboardList,
  discord: MessageCircle,
  auxiliary: Wrench,
};

function CategoryIcon({
  category,
  className,
}: {
  category: string;
  className?: string;
}) {
  const Icon = CATEGORY_ICONS[category] ?? FileQuestion;
  return <Icon className={className ?? "h-4 w-4"} />;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ConfigPage() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [schema, setSchema] = useState<Record<
    string,
    Record<string, unknown>
  > | null>(null);
  const [categoryOrder, setCategoryOrder] = useState<string[]>([]);
  const [defaults, setDefaults] = useState<Record<string, unknown> | null>(
    null,
  );
  const [modelOptions, setModelOptions] = useState<ModelOptionsResponse | null>(
    null,
  );
  const [modelSwitchSaving, setModelSwitchSaving] = useState<
    "main" | "memory" | null
  >(null);
  const [modelProviderSaving, setModelProviderSaving] = useState(false);
  const [modelProviderForm, setModelProviderForm] = useState({
    name: "",
    slug: "",
    baseUrl: "",
    apiKey: "",
    keyEnv: "",
    defaultModel: "",
    apiMode: "chat_completions",
    models: "",
  });
  const [saving, setSaving] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [yamlMode, setYamlMode] = useState(false);
  const [yamlText, setYamlText] = useState("");
  const [yamlLoading, setYamlLoading] = useState(false);
  const [yamlSaving, setYamlSaving] = useState(false);
  const [activeCategory, setActiveCategory] = useState<string>("");
  const { toast, showToast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { t } = useI18n();
  const { setEnd } = usePageHeader();

  useLayoutEffect(() => {
    if (!config || !schema) {
      setEnd(null);
      return;
    }
    setEnd(
      <div className="relative w-full min-w-0 sm:max-w-xs">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
        <Input
          className="h-8 pl-8 pr-7 text-xs"
          placeholder={t.common.search}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        {searchQuery && (
          <button
            type="button"
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            onClick={() => setSearchQuery("")}
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </div>,
    );
    return () => setEnd(null);
  }, [config, schema, searchQuery, setEnd, t.common.search]);

  function prettyCategoryName(cat: string): string {
    const key = cat as keyof typeof t.config.categories;
    if (t.config.categories[key]) return t.config.categories[key];
    return cat.charAt(0).toUpperCase() + cat.slice(1);
  }

  useEffect(() => {
    api
      .getConfig()
      .then(setConfig)
      .catch(() => {});
    api
      .getModelOptions()
      .then(setModelOptions)
      .catch(() => {});
    api
      .getSchema()
      .then((resp) => {
        setSchema(resp.fields as Record<string, Record<string, unknown>>);
        setCategoryOrder(resp.category_order ?? []);
      })
      .catch(() => {});
    api
      .getDefaults()
      .then(setDefaults)
      .catch(() => {});
  }, []);

  // Set active category when categories load
  useEffect(() => {
    if (categoryOrder.length > 0 && !activeCategory) {
      setActiveCategory(categoryOrder[0]);
    }
  }, [categoryOrder, activeCategory]);

  // Load YAML when switching to YAML mode
  useEffect(() => {
    if (yamlMode) {
      setYamlLoading(true);
      api
        .getConfigRaw()
        .then((resp) => setYamlText(resp.yaml))
        .catch(() => showToast(t.config.failedToLoadRaw, "error"))
        .finally(() => setYamlLoading(false));
    }
  }, [showToast, t.config.failedToLoadRaw, yamlMode]);

  /* ---- Categories ---- */
  const categories = useMemo(() => {
    if (!schema) return [];
    const allCats = [
      ...new Set(
        Object.values(schema).map((s) => String(s.category ?? "general")),
      ),
    ];
    const ordered = categoryOrder.filter((c) => allCats.includes(c));
    const extra = allCats.filter((c) => !categoryOrder.includes(c)).sort();
    return [...ordered, ...extra];
  }, [schema, categoryOrder]);

  /* ---- Category field counts ---- */
  const categoryCounts = useMemo(() => {
    if (!schema) return {};
    const counts: Record<string, number> = {};
    for (const s of Object.values(schema)) {
      const cat = String(s.category ?? "general");
      counts[cat] = (counts[cat] || 0) + 1;
    }
    return counts;
  }, [schema]);

  /* ---- Search ---- */
  const isSearching = searchQuery.trim().length > 0;
  const lowerSearch = searchQuery.toLowerCase();

  const searchMatchedFields = useMemo(() => {
    if (!isSearching || !schema) return [];
    return Object.entries(schema).filter(([key, s]) => {
      const label = key.split(".").pop() ?? key;
      const humanLabel = label.replace(/_/g, " ");
      return (
        key.toLowerCase().includes(lowerSearch) ||
        humanLabel.toLowerCase().includes(lowerSearch) ||
        String(s.category ?? "")
          .toLowerCase()
          .includes(lowerSearch) ||
        String(s.description ?? "")
          .toLowerCase()
          .includes(lowerSearch)
      );
    });
  }, [isSearching, lowerSearch, schema]);

  /* ---- Active tab fields ---- */
  const activeFields = useMemo(() => {
    if (!schema || isSearching) return [];
    return Object.entries(schema).filter(
      ([, s]) => String(s.category ?? "general") === activeCategory,
    );
  }, [schema, activeCategory, isSearching]);

  /* ---- Handlers ---- */
  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await api.saveConfig(config);
      showToast(t.config.configSaved, "success");
    } catch (e) {
      showToast(`${t.config.failedToSave}: ${e}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const handleYamlSave = async () => {
    setYamlSaving(true);
    try {
      await api.saveConfigRaw(yamlText);
      showToast(t.config.yamlConfigSaved, "success");
      api
        .getConfig()
        .then(setConfig)
        .catch(() => {});
    } catch (e) {
      showToast(`${t.config.failedToSaveYaml}: ${e}`, "error");
    } finally {
      setYamlSaving(false);
    }
  };

  const handleReset = () => {
    if (defaults) setConfig(structuredClone(defaults));
  };

  const handleExport = () => {
    if (!config) return;
    const blob = new Blob([JSON.stringify(config, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "mente-config.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const imported = JSON.parse(reader.result as string);
        setConfig(imported);
        showToast(t.config.configImported, "success");
      } catch {
        showToast(t.config.invalidJson, "error");
      }
    };
    reader.readAsText(file);
  };

  const refreshModelState = async () => {
    const [nextConfig, nextOptions] = await Promise.all([
      api.getConfig(),
      api.getModelOptions(),
    ]);
    setConfig(nextConfig);
    setModelOptions(nextOptions);
  };

  const handleQuickModelSwitch = async (
    target: "main" | "memory",
    provider: string,
    model?: string,
  ) => {
    setModelSwitchSaving(target);
    try {
      await api.quickSwitchModel({ target, provider, model });
      await refreshModelState();
      showToast(t.config.modelSwitchSaved, "success");
    } catch (e) {
      showToast(`${t.config.failedToSave}: ${e}`, "error");
    } finally {
      setModelSwitchSaving(null);
    }
  };

  const handleCreateModelProvider = async (event: React.FormEvent) => {
    event.preventDefault();
    const payload: ModelProviderCreateRequest = {
      name: modelProviderForm.name.trim(),
      slug: modelProviderForm.slug.trim(),
      base_url: modelProviderForm.baseUrl.trim(),
      api_key: modelProviderForm.apiKey,
      key_env: modelProviderForm.keyEnv.trim(),
      default_model: modelProviderForm.defaultModel.trim(),
      api_mode: modelProviderForm.apiMode,
      models: modelProviderForm.models
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean),
    };
    if (!payload.name || !payload.base_url || !payload.default_model) {
      showToast(t.config.modelProviderRequired, "error");
      return;
    }

    setModelProviderSaving(true);
    try {
      await api.createModelProvider(payload);
      await refreshModelState();
      setModelProviderForm({
        name: "",
        slug: "",
        baseUrl: "",
        apiKey: "",
        keyEnv: "",
        defaultModel: "",
        apiMode: "chat_completions",
        models: "",
      });
      showToast(t.config.modelProviderSaved, "success");
    } catch (e) {
      showToast(`${t.config.failedToSave}: ${e}`, "error");
    } finally {
      setModelProviderSaving(false);
    }
  };

  const updateModelProviderForm = (
    key: keyof typeof modelProviderForm,
    value: string,
  ) => {
    setModelProviderForm((current) => ({ ...current, [key]: value }));
  };

  const providerMap = useMemo(() => {
    const map = new Map<string, ModelProviderOption>();
    for (const provider of modelOptions?.providers ?? []) {
      map.set(provider.slug, provider);
    }
    return map;
  }, [modelOptions]);

  const modelsForProvider = (
    providerSlug: string,
    currentModel: string,
  ): string[] => {
    const provider = providerMap.get(providerSlug);
    const models = [...(provider?.models ?? [])];
    const defaultModel = provider?.default_model;
    if (defaultModel && !models.includes(defaultModel))
      models.unshift(defaultModel);
    if (currentModel && !models.includes(currentModel))
      models.unshift(currentModel);
    return models;
  };

  const defaultModelForProvider = (providerSlug: string): string => {
    const provider = providerMap.get(providerSlug);
    return provider?.default_model || provider?.models?.[0] || "";
  };

  const renderModelQuickSwitchRow = (target: "main" | "memory") => {
    if (!modelOptions) return null;
    const selection = modelOptions.current[target];
    const isMemory = target === "memory";
    const providerValue = isMemory
      ? selection.provider || "auto"
      : selection.provider;
    const provider = providerMap.get(providerValue);
    const models =
      isMemory && providerValue === "auto"
        ? []
        : modelsForProvider(providerValue, selection.model);
    const modelValue =
      isMemory && providerValue === "auto"
        ? "auto"
        : selection.model || defaultModelForProvider(providerValue);
    const busy = modelSwitchSaving === target;

    return (
      <div className="grid gap-3 border border-border/70 bg-background/35 p-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            {isMemory ? (
              <Brain className="h-4 w-4 text-muted-foreground" />
            ) : (
              <Bot className="h-4 w-4 text-muted-foreground" />
            )}
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.12em]">
                {isMemory ? t.config.memoryModel : t.config.mainModel}
              </div>
              <div className="text-[11px] text-muted-foreground">
                {providerValue === "auto"
                  ? t.config.autoMemoryModel
                  : `${provider?.name ?? providerValue} · ${selection.model || modelValue}`}
              </div>
            </div>
          </div>
          {busy && (
            <Badge variant="outline" className="text-[10px]">
              {t.config.applying}
            </Badge>
          )}
        </div>

        <div className="grid gap-2 md:grid-cols-2">
          <Select
            value={providerValue}
            disabled={!!modelSwitchSaving}
            onValueChange={(nextProvider) => {
              const nextModel =
                nextProvider === "auto"
                  ? ""
                  : defaultModelForProvider(nextProvider);
              handleQuickModelSwitch(target, nextProvider, nextModel);
            }}
          >
            {isMemory && (
              <SelectOption value="auto">
                {t.config.autoMemoryModel}
              </SelectOption>
            )}
            {(modelOptions.providers ?? []).map((item) => (
              <SelectOption key={item.slug} value={item.slug}>
                {item.name || item.slug}
              </SelectOption>
            ))}
          </Select>

          <Select
            value={modelValue}
            disabled={
              !!modelSwitchSaving ||
              providerValue === "auto" ||
              models.length === 0
            }
            onValueChange={(nextModel) =>
              handleQuickModelSwitch(target, providerValue, nextModel)
            }
          >
            {providerValue === "auto" ? (
              <SelectOption value="auto">
                {t.config.autoMemoryModel}
              </SelectOption>
            ) : models.length > 0 ? (
              models.map((model) => (
                <SelectOption key={model} value={model}>
                  {model}
                </SelectOption>
              ))
            ) : (
              <SelectOption value={modelValue || ""}>
                {t.config.noModelChoices}
              </SelectOption>
            )}
          </Select>
        </div>

        {(selection.base_url || provider?.api_url) && (
          <div className="truncate font-mono text-[11px] text-muted-foreground">
            {t.config.currentEndpoint}:{" "}
            {selection.base_url || provider?.api_url}
          </div>
        )}
      </div>
    );
  };

  const renderModelProviderForm = () => (
    <form
      onSubmit={handleCreateModelProvider}
      className="grid gap-3 border border-border/70 bg-background/35 p-3 lg:col-span-2"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-2">
          <div className="mt-0.5 border border-border bg-background/60 p-1.5">
            <KeyRound className="h-4 w-4 text-muted-foreground" />
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.12em]">
              {t.config.addModelProvider}
            </div>
            <div className="mt-1 max-w-2xl text-[11px] text-muted-foreground">
              {t.config.addModelProviderHint}
            </div>
          </div>
        </div>
        <Badge variant="outline" className="w-fit text-[10px]">
          providers + .env
        </Badge>
      </div>

      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        <div className="grid gap-1.5">
          <span className="text-[11px] text-muted-foreground">
            {t.config.providerName}
          </span>
          <Input
            value={modelProviderForm.name}
            onChange={(e) => updateModelProviderForm("name", e.target.value)}
            placeholder="My Relay"
          />
        </div>
        <div className="grid gap-1.5">
          <span className="text-[11px] text-muted-foreground">
            {t.config.providerSlug}
          </span>
          <Input
            value={modelProviderForm.slug}
            onChange={(e) => updateModelProviderForm("slug", e.target.value)}
            placeholder="my-relay"
          />
        </div>
        <div className="grid gap-1.5 md:col-span-2">
          <span className="text-[11px] text-muted-foreground">
            {t.config.providerBaseUrl}
          </span>
          <Input
            value={modelProviderForm.baseUrl}
            onChange={(e) => updateModelProviderForm("baseUrl", e.target.value)}
            placeholder="https://relay.example.com/v1"
          />
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        <div className="grid gap-1.5">
          <span className="text-[11px] text-muted-foreground">
            {t.config.providerDefaultModel}
          </span>
          <Input
            value={modelProviderForm.defaultModel}
            onChange={(e) =>
              updateModelProviderForm("defaultModel", e.target.value)
            }
            placeholder="gpt-5.4-mini"
          />
        </div>
        <div className="grid gap-1.5">
          <span className="text-[11px] text-muted-foreground">
            {t.config.providerApiMode}
          </span>
          <Select
            value={modelProviderForm.apiMode}
            onValueChange={(value) => updateModelProviderForm("apiMode", value)}
          >
            <SelectOption value="chat_completions">
              chat_completions
            </SelectOption>
            <SelectOption value="anthropic_messages">
              anthropic_messages
            </SelectOption>
            <SelectOption value="codex_responses">
              codex_responses
            </SelectOption>
          </Select>
        </div>
        <div className="grid gap-1.5">
          <span className="text-[11px] text-muted-foreground">
            {t.config.providerKeyEnv}
          </span>
          <Input
            value={modelProviderForm.keyEnv}
            onChange={(e) => updateModelProviderForm("keyEnv", e.target.value)}
            placeholder="MY_RELAY_API_KEY"
          />
        </div>
        <div className="grid gap-1.5">
          <span className="text-[11px] text-muted-foreground">
            {t.config.providerApiKey}
          </span>
          <Input
            type="password"
            value={modelProviderForm.apiKey}
            onChange={(e) => updateModelProviderForm("apiKey", e.target.value)}
            placeholder="sk-..."
          />
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-[1fr_auto] md:items-end">
        <div className="grid gap-1.5">
          <span className="text-[11px] text-muted-foreground">
            {t.config.providerModels}
          </span>
          <textarea
            className="min-h-20 w-full border border-border bg-background/40 px-3 py-2 font-courier text-sm transition-colors placeholder:text-muted-foreground focus-visible:border-foreground/25 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/30"
            value={modelProviderForm.models}
            onChange={(e) => updateModelProviderForm("models", e.target.value)}
            placeholder={"gpt-5.4-mini\ndeepseek-chat\nclaude-sonnet-4.6"}
          />
        </div>
        <Button
          type="submit"
          size="sm"
          disabled={modelProviderSaving}
          className="gap-1.5"
        >
          <Plus className="h-3.5 w-3.5" />
          {modelProviderSaving ? t.common.saving : t.config.saveModelProvider}
        </Button>
      </div>
    </form>
  );

  /* ---- Loading ---- */
  if (!config || !schema) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  /* ---- Render field list (shared between search & normal) ---- */
  const renderFields = (
    fields: [string, Record<string, unknown>][],
    showCategory = false,
  ) => {
    let lastSection = "";
    let lastCat = "";
    return fields.map(([key, s]) => {
      const parts = key.split(".");
      const section = parts.length > 1 ? parts[0] : "";
      const cat = String(s.category ?? "general");
      const showCatBadge = showCategory && cat !== lastCat;
      const showSection =
        !showCategory &&
        section &&
        section !== lastSection &&
        section !== activeCategory;
      lastSection = section;
      lastCat = cat;

      return (
        <div key={key}>
          {showCatBadge && (
            <div className="flex items-center gap-2 pt-4 pb-2 first:pt-0">
              <CategoryIcon
                category={cat}
                className="h-4 w-4 text-muted-foreground"
              />
              <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {prettyCategoryName(cat)}
              </span>
              <div className="flex-1 border-t border-border" />
            </div>
          )}
          {showSection && (
            <div className="flex items-center gap-2 pt-4 pb-2 first:pt-0">
              <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {section.replace(/_/g, " ")}
              </span>
              <div className="flex-1 border-t border-border" />
            </div>
          )}
          <div className="py-1">
            <AutoField
              schemaKey={key}
              schema={s}
              value={getNestedValue(config, key)}
              onChange={(v) => setConfig(setNestedValue(config, key, v))}
            />
          </div>
        </div>
      );
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <PluginSlot name="config:top" />
      <Toast toast={toast} />

      {/* ═══════════════ Header Bar ═══════════════ */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Settings2 className="h-4 w-4 text-muted-foreground" />
          <code className="text-xs text-muted-foreground bg-muted/50 px-2 py-0.5">
            {t.config.configPath}
          </code>
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleExport}
            title={t.config.exportConfig}
            aria-label={t.config.exportConfig}
          >
            <Download className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            title={t.config.importConfig}
            aria-label={t.config.importConfig}
          >
            <Upload className="h-3.5 w-3.5" />
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={handleImport}
          />
          <Button
            variant="ghost"
            size="sm"
            onClick={handleReset}
            title={t.config.resetDefaults}
            aria-label={t.config.resetDefaults}
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </Button>

          <div className="w-px h-5 bg-border mx-1" />

          <Button
            variant={yamlMode ? "default" : "outline"}
            size="sm"
            onClick={() => setYamlMode(!yamlMode)}
            className="gap-1.5"
          >
            {yamlMode ? (
              <>
                <FormInput className="h-3.5 w-3.5" />
                {t.common.form}
              </>
            ) : (
              <>
                <Code className="h-3.5 w-3.5" />
                YAML
              </>
            )}
          </Button>

          {yamlMode ? (
            <Button
              size="sm"
              onClick={handleYamlSave}
              disabled={yamlSaving}
              className="gap-1.5"
            >
              <Save className="h-3.5 w-3.5" />
              {yamlSaving ? t.common.saving : t.common.save}
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={handleSave}
              disabled={saving}
              className="gap-1.5"
            >
              <Save className="h-3.5 w-3.5" />
              {saving ? t.common.saving : t.common.save}
            </Button>
          )}
        </div>
      </div>

      {/* ═══════════════ YAML Mode ═══════════════ */}
      {yamlMode ? (
        <Card>
          <CardHeader className="py-3 px-4">
            <CardTitle className="text-sm flex items-center gap-2">
              <FileText className="h-4 w-4" />
              {t.config.rawYaml}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {yamlLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              </div>
            ) : (
              <textarea
                className="flex min-h-[600px] w-full bg-transparent px-4 py-3 text-sm font-mono leading-relaxed placeholder:text-muted-foreground focus-visible:outline-none border-t border-border"
                value={yamlText}
                onChange={(e) => setYamlText(e.target.value)}
                spellCheck={false}
              />
            )}
          </CardContent>
        </Card>
      ) : (
        /* ═══════════════ Form Mode ═══════════════ */
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader className="py-3 px-4">
              <CardTitle className="text-sm flex items-center gap-2">
                <Settings2 className="h-4 w-4" />
                {t.config.modelQuickSwitch}
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 px-4 pb-4 lg:grid-cols-2">
              {renderModelQuickSwitchRow("main")}
              {renderModelQuickSwitchRow("memory")}
              {renderModelProviderForm()}
            </CardContent>
          </Card>

          <div className="flex flex-col sm:flex-row gap-4">
            {/* ---- Filter panel ---- */}
            <aside
              aria-label={t.config.filters}
              className="sm:w-56 sm:shrink-0"
            >
              <div className="sm:sticky sm:top-4">
                <div className="flex flex-col border border-border bg-muted/20">
                  {/* Panel heading */}
                  <div className="hidden sm:flex items-center gap-2 px-3 py-2 border-b border-border">
                    <Filter className="h-3 w-3 text-muted-foreground" />
                    <span className="font-mondwest text-[0.65rem] tracking-[0.12em] uppercase text-muted-foreground">
                      {t.config.filters}
                    </span>
                  </div>

                  {/* Sections heading (hidden on mobile since it becomes a horizontal scroll) */}
                  <div className="hidden sm:block px-3 pt-2 pb-1 font-mondwest text-[0.6rem] tracking-[0.12em] uppercase text-muted-foreground/70">
                    {t.config.sections}
                  </div>

                  {/* Category nav — horizontal scroll on mobile, pill list on sm+ */}
                  <div className="flex sm:flex-col gap-1 sm:gap-px p-2 sm:pt-1 overflow-x-auto sm:overflow-x-visible scrollbar-none sm:max-h-[calc(100vh-260px)] sm:overflow-y-auto">
                    {categories.map((cat) => {
                      const isActive = !isSearching && activeCategory === cat;

                      return (
                        <button
                          key={cat}
                          type="button"
                          onClick={() => {
                            setSearchQuery("");
                            setActiveCategory(cat);
                          }}
                          className={`
                          group flex items-center gap-2 px-2 py-1
                          rounded-sm text-left text-[11px] cursor-pointer whitespace-nowrap
                          transition-colors
                          ${
                            isActive
                              ? "bg-foreground/10 text-foreground"
                              : "text-muted-foreground hover:text-foreground hover:bg-foreground/5"
                          }
                        `}
                        >
                          <CategoryIcon
                            category={cat}
                            className="h-3.5 w-3.5 shrink-0"
                          />
                          <span className="flex-1 truncate">
                            {prettyCategoryName(cat)}
                          </span>
                          <span
                            className={`text-[10px] tabular-nums ${
                              isActive
                                ? "text-foreground/60"
                                : "text-muted-foreground/50"
                            }`}
                          >
                            {categoryCounts[cat] || 0}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            </aside>

            {/* ---- Content ---- */}
            <div className="flex-1 min-w-0">
              {isSearching ? (
                /* Search results */
                <Card>
                  <CardHeader className="py-3 px-4">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <Search className="h-4 w-4" />
                        {t.config.searchResults}
                      </CardTitle>
                      <Badge variant="secondary" className="text-[10px]">
                        {searchMatchedFields.length}{" "}
                        {t.config.fields.replace(
                          "{s}",
                          searchMatchedFields.length !== 1 ? "s" : "",
                        )}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="grid gap-2 px-4 pb-4">
                    {searchMatchedFields.length === 0 ? (
                      <p className="text-sm text-muted-foreground text-center py-8">
                        {t.config.noFieldsMatch.replace("{query}", searchQuery)}
                      </p>
                    ) : (
                      renderFields(searchMatchedFields, true)
                    )}
                  </CardContent>
                </Card>
              ) : (
                /* Active category */
                <Card>
                  <CardHeader className="py-3 px-4">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <CategoryIcon
                          category={activeCategory}
                          className="h-4 w-4"
                        />
                        {prettyCategoryName(activeCategory)}
                      </CardTitle>
                      <Badge variant="secondary" className="text-[10px]">
                        {activeFields.length}{" "}
                        {t.config.fields.replace(
                          "{s}",
                          activeFields.length !== 1 ? "s" : "",
                        )}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="grid gap-2 px-4 pb-4">
                    {renderFields(activeFields)}
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        </div>
      )}
      <PluginSlot name="config:bottom" />
    </div>
  );
}
