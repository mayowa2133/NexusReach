import { useState, useMemo } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Checkbox } from '@/components/ui/checkbox';
import { Separator } from '@/components/ui/separator';
import { useProfile, useUpdateProfile, useUploadResume, getProfileCompletion } from '@/hooks/useProfile';
import { useStories, useCreateStory, useUpdateStory, useDeleteStory } from '@/hooks/useStories';
import { toast } from 'sonner';
import type { Profile, Story, StoryInput } from '@/types';

const GOALS = ['job', 'mentor', 'network'] as const;
const TONES = ['formal', 'conversational', 'humble'] as const;
const STEPS = ['Basics', 'Goals & Targets', 'Resume', 'Links', 'Stories'] as const;

type FormData = {
  full_name: string;
  bio: string;
  goals: string[];
  tone: 'formal' | 'conversational' | 'humble';
  target_industries: string[];
  target_company_sizes: string[];
  target_roles: string[];
  target_locations: string[];
  linkedin_url: string;
  github_url: string;
  portfolio_url: string;
};

function profileToForm(profile: Profile | undefined): FormData {
  return {
    full_name: profile?.full_name ?? '',
    bio: profile?.bio ?? '',
    goals: profile?.goals ?? [],
    tone: profile?.tone ?? 'conversational',
    target_industries: profile?.target_industries ?? [],
    target_company_sizes: profile?.target_company_sizes ?? [],
    target_roles: profile?.target_roles ?? [],
    target_locations: profile?.target_locations ?? [],
    linkedin_url: profile?.linkedin_url ?? '',
    github_url: profile?.github_url ?? '',
    portfolio_url: profile?.portfolio_url ?? '',
  };
}

export function ProfilePage() {
  const { data: profile, isLoading } = useProfile();
  const updateProfile = useUpdateProfile();
  const uploadResume = useUploadResume();
  const [step, setStep] = useState(0);
  const initialForm = useMemo(() => profileToForm(profile), [profile]);
  const [form, setForm] = useState<FormData>(profileToForm(undefined));
  const [formSynced, setFormSynced] = useState(false);
  const [tagInput, setTagInput] = useState({ industries: '', roles: '', locations: '', sizes: '' });

  // Sync form with profile data when it first loads (avoids setState in useEffect)
  if (profile && !formSynced) {
    setForm(initialForm);
    setFormSynced(true);
  }

  const { percentage, missing } = getProfileCompletion(profile);

  const updateField = <K extends keyof FormData>(key: K, value: FormData[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    try {
      await updateProfile.mutateAsync(form);
      toast.success('Profile saved');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save');
    }
  };

  const handleResumeUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const validTypes = [
      'application/pdf',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    ];
    if (!validTypes.includes(file.type)) {
      toast.error('Please upload a PDF or DOCX file');
      return;
    }

    try {
      await uploadResume.mutateAsync(file);
      toast.success('Resume uploaded and parsed');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Upload failed');
    }
  };

  const addTag = (field: 'target_industries' | 'target_roles' | 'target_locations' | 'target_company_sizes', inputKey: keyof typeof tagInput) => {
    const value = tagInput[inputKey].trim();
    if (!value) return;
    if (!form[field].includes(value)) {
      updateField(field, [...form[field], value]);
    }
    setTagInput((prev) => ({ ...prev, [inputKey]: '' }));
  };

  const removeTag = (field: 'target_industries' | 'target_roles' | 'target_locations' | 'target_company_sizes', value: string) => {
    updateField(field, form[field].filter((v) => v !== value));
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-muted-foreground">Loading profile...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Profile</h1>
          <p className="text-muted-foreground">
            Your professional profile — the foundation for every message.
          </p>
        </div>
        <div className="text-right">
          <div className="text-sm text-muted-foreground mb-1">{percentage}% complete</div>
          <Progress value={percentage} className="w-32" />
        </div>
      </div>

      {missing.length > 0 && (
        <div className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
          Missing: {missing.join(', ')}
        </div>
      )}

      {/* Step navigation */}
      <div className="flex gap-2">
        {STEPS.map((label, i) => (
          <Button
            key={label}
            variant={step === i ? 'default' : 'outline'}
            size="sm"
            onClick={() => setStep(i)}
          >
            {label}
          </Button>
        ))}
      </div>

      <Separator />

      {/* Step 0: Basics */}
      {step === 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Basic Information</CardTitle>
            <CardDescription>Tell us about yourself.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="full_name">Full Name</Label>
              <Input
                id="full_name"
                placeholder="Your full name"
                value={form.full_name}
                onChange={(e) => updateField('full_name', e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="bio">Bio</Label>
              <Textarea
                id="bio"
                placeholder="Write a short description of who you are, what you're passionate about, and what you're looking for. This feeds into every message the AI drafts for you."
                rows={4}
                value={form.bio}
                onChange={(e) => updateField('bio', e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Write in your own voice — the AI uses this to make messages sound like you.
              </p>
            </div>

            <div className="space-y-2">
              <Label>Tone Preference</Label>
              <div className="flex gap-2">
                {TONES.map((tone) => (
                  <Button
                    key={tone}
                    variant={form.tone === tone ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => updateField('tone', tone as FormData['tone'])}
                  >
                    {tone.charAt(0).toUpperCase() + tone.slice(1)}
                  </Button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                Controls the voice of AI-drafted messages.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 1: Goals & Targets */}
      {step === 1 && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Your Goals</CardTitle>
              <CardDescription>What are you looking to achieve?</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {GOALS.map((goal) => (
                <div key={goal} className="flex items-center gap-3">
                  <Checkbox
                    id={`goal-${goal}`}
                    checked={form.goals.includes(goal)}
                    onCheckedChange={(checked) => {
                      if (checked) {
                        updateField('goals', [...form.goals, goal]);
                      } else {
                        updateField('goals', form.goals.filter((g) => g !== goal));
                      }
                    }}
                  />
                  <Label htmlFor={`goal-${goal}`} className="cursor-pointer">
                    {goal === 'job' && 'Find a Job'}
                    {goal === 'mentor' && 'Find a Mentor'}
                    {goal === 'network' && 'Grow My Network'}
                  </Label>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Target Preferences</CardTitle>
              <CardDescription>Help us find the right opportunities for you.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <TagField
                label="Target Industries"
                placeholder="e.g. Fintech, AI/ML, Healthcare"
                tags={form.target_industries}
                inputValue={tagInput.industries}
                onInputChange={(v) => setTagInput((p) => ({ ...p, industries: v }))}
                onAdd={() => addTag('target_industries', 'industries')}
                onRemove={(v) => removeTag('target_industries', v)}
              />
              <TagField
                label="Target Roles"
                placeholder="e.g. Software Engineer, Backend Developer"
                tags={form.target_roles}
                inputValue={tagInput.roles}
                onInputChange={(v) => setTagInput((p) => ({ ...p, roles: v }))}
                onAdd={() => addTag('target_roles', 'roles')}
                onRemove={(v) => removeTag('target_roles', v)}
              />
              <TagField
                label="Target Locations"
                placeholder="e.g. Toronto, Remote, San Francisco"
                tags={form.target_locations}
                inputValue={tagInput.locations}
                onInputChange={(v) => setTagInput((p) => ({ ...p, locations: v }))}
                onAdd={() => addTag('target_locations', 'locations')}
                onRemove={(v) => removeTag('target_locations', v)}
              />
              <TagField
                label="Company Sizes"
                placeholder="e.g. Startup, Mid-size, Enterprise"
                tags={form.target_company_sizes}
                inputValue={tagInput.sizes}
                onInputChange={(v) => setTagInput((p) => ({ ...p, sizes: v }))}
                onAdd={() => addTag('target_company_sizes', 'sizes')}
                onRemove={(v) => removeTag('target_company_sizes', v)}
              />
            </CardContent>
          </Card>
        </div>
      )}

      {/* Step 2: Resume */}
      {step === 2 && (
        <Card>
          <CardHeader>
            <CardTitle>Resume</CardTitle>
            <CardDescription>
              Upload your resume so the AI can reference your real experience.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="resume-upload">Upload Resume (PDF or DOCX)</Label>
              <Input
                id="resume-upload"
                type="file"
                accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={handleResumeUpload}
                disabled={uploadResume.isPending}
              />
              {uploadResume.isPending && (
                <p className="text-sm text-muted-foreground">Parsing resume...</p>
              )}
            </div>

            {profile?.resume_parsed && (
              <div className="space-y-4">
                <Separator />
                <h3 className="font-medium">Parsed Resume</h3>

                {profile.resume_parsed.skills?.length > 0 && (
                  <div className="space-y-1">
                    <Label className="text-muted-foreground">Skills</Label>
                    <div className="flex flex-wrap gap-1">
                      {profile.resume_parsed.skills.map((skill: string) => (
                        <Badge key={skill} variant="secondary">{skill}</Badge>
                      ))}
                    </div>
                  </div>
                )}

                {profile.resume_parsed.experience?.length > 0 && (
                  <div className="space-y-2">
                    <Label className="text-muted-foreground">Experience</Label>
                    {profile.resume_parsed.experience.map((exp: { company: string; title: string; start_date: string; end_date: string | null; description: string }, i: number) => (
                      <div key={i} className="rounded-lg border p-3">
                        <div className="font-medium">{exp.title}</div>
                        <div className="text-sm text-muted-foreground">
                          {exp.company} &middot; {exp.start_date} — {exp.end_date ?? 'Present'}
                        </div>
                        {exp.description && (
                          <p className="mt-1 text-sm">{exp.description}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {profile.resume_parsed.education?.length > 0 && (
                  <div className="space-y-2">
                    <Label className="text-muted-foreground">Education</Label>
                    {profile.resume_parsed.education.map((edu: { institution: string; degree: string; field: string; graduation_date: string }, i: number) => (
                      <div key={i} className="rounded-lg border p-3">
                        <div className="font-medium">{edu.degree} in {edu.field}</div>
                        <div className="text-sm text-muted-foreground">
                          {edu.institution} &middot; {edu.graduation_date}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {profile.resume_parsed.projects?.length > 0 && (
                  <div className="space-y-2">
                    <Label className="text-muted-foreground">Projects</Label>
                    {profile.resume_parsed.projects.map((proj: { name: string; description: string; technologies: string[]; url: string | null }, i: number) => (
                      <div key={i} className="rounded-lg border p-3">
                        <div className="font-medium">{proj.name}</div>
                        <p className="mt-1 text-sm">{proj.description}</p>
                        {proj.technologies?.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {proj.technologies.map((t: string) => (
                              <Badge key={t} variant="outline" className="text-xs">{t}</Badge>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Step 3: Links */}
      {step === 3 && (
        <Card>
          <CardHeader>
            <CardTitle>Portfolio Links</CardTitle>
            <CardDescription>Connect your profiles for richer outreach.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="linkedin_url">LinkedIn URL</Label>
              <Input
                id="linkedin_url"
                placeholder="https://linkedin.com/in/yourname"
                value={form.linkedin_url}
                onChange={(e) => updateField('linkedin_url', e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="github_url">GitHub URL</Label>
              <Input
                id="github_url"
                placeholder="https://github.com/yourname"
                value={form.github_url}
                onChange={(e) => updateField('github_url', e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="portfolio_url">Portfolio / Personal Site</Label>
              <Input
                id="portfolio_url"
                placeholder="https://yoursite.com"
                value={form.portfolio_url}
                onChange={(e) => updateField('portfolio_url', e.target.value)}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 4: Stories */}
      {step === 4 && <StoryBankSection />}

      {/* Navigation + Save */}
      <div className="flex items-center justify-between">
        <Button
          variant="outline"
          onClick={() => setStep((s) => s - 1)}
          disabled={step === 0}
        >
          Previous
        </Button>
        <div className="flex gap-2">
          <Button
            onClick={handleSave}
            variant="outline"
            disabled={updateProfile.isPending}
          >
            {updateProfile.isPending ? 'Saving...' : 'Save'}
          </Button>
          {step < STEPS.length - 1 ? (
            <Button onClick={() => { handleSave(); setStep((s) => s + 1); }}>
              Save & Continue
            </Button>
          ) : (
            <Button onClick={handleSave} disabled={updateProfile.isPending}>
              Finish
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

function TagField({
  label,
  placeholder,
  tags,
  inputValue,
  onInputChange,
  onAdd,
  onRemove,
}: {
  label: string;
  placeholder: string;
  tags: string[];
  inputValue: string;
  onInputChange: (v: string) => void;
  onAdd: () => void;
  onRemove: (v: string) => void;
}) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <div className="flex gap-2">
        <Input
          placeholder={placeholder}
          value={inputValue}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              onAdd();
            }
          }}
        />
        <Button variant="outline" size="sm" onClick={onAdd} type="button">
          Add
        </Button>
      </div>
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {tags.map((tag) => (
            <Badge key={tag} variant="secondary" className="cursor-pointer" onClick={() => onRemove(tag)}>
              {tag} &times;
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

const EMPTY_STORY: StoryInput = {
  title: '',
  summary: '',
  situation: '',
  action: '',
  result: '',
  impact_metric: '',
  role_focus: '',
  tags: [],
};

function StoryBankSection() {
  const { data: stories = [], isLoading } = useStories();
  const createStory = useCreateStory();
  const updateStory = useUpdateStory();
  const deleteStory = useDeleteStory();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<StoryInput>(EMPTY_STORY);
  const [tagInput, setTagInput] = useState('');
  const [showForm, setShowForm] = useState(false);

  const startCreate = () => {
    setEditingId(null);
    setDraft(EMPTY_STORY);
    setTagInput('');
    setShowForm(true);
  };

  const startEdit = (story: Story) => {
    setEditingId(story.id);
    setDraft({
      title: story.title,
      summary: story.summary ?? '',
      situation: story.situation ?? '',
      action: story.action ?? '',
      result: story.result ?? '',
      impact_metric: story.impact_metric ?? '',
      role_focus: story.role_focus ?? '',
      tags: story.tags ?? [],
    });
    setTagInput('');
    setShowForm(true);
  };

  const cancel = () => {
    setShowForm(false);
    setEditingId(null);
    setDraft(EMPTY_STORY);
    setTagInput('');
  };

  const addTagToDraft = () => {
    const v = tagInput.trim().toLowerCase();
    if (!v) return;
    if ((draft.tags ?? []).includes(v)) {
      setTagInput('');
      return;
    }
    setDraft((prev) => ({ ...prev, tags: [...(prev.tags ?? []), v] }));
    setTagInput('');
  };

  const removeTagFromDraft = (tag: string) => {
    setDraft((prev) => ({ ...prev, tags: (prev.tags ?? []).filter((t) => t !== tag) }));
  };

  const save = async () => {
    if (!draft.title.trim()) {
      toast.error('Title required');
      return;
    }
    try {
      if (editingId) {
        await updateStory.mutateAsync({ id: editingId, payload: draft });
        toast.success('Story updated');
      } else {
        await createStory.mutateAsync(draft);
        toast.success('Story added');
      }
      cancel();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save');
    }
  };

  const remove = async (id: string) => {
    if (!confirm('Delete this story?')) return;
    try {
      await deleteStory.mutateAsync(id);
      toast.success('Story deleted');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete');
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle>Story Bank</CardTitle>
            <CardDescription>
              Reusable proof points the AI can weave into outreach drafts. Use STAR (Situation, Action, Result) and add tags for the contexts they fit.
            </CardDescription>
          </div>
          {!showForm && (
            <Button size="sm" onClick={startCreate}>
              Add Story
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {showForm && (
          <div className="rounded-lg border p-4 space-y-3 bg-muted/30">
            <div className="space-y-2">
              <Label htmlFor="story-title">Title</Label>
              <Input
                id="story-title"
                placeholder="e.g. Cut deploy time 40% via CI rewrite"
                value={draft.title}
                onChange={(e) => setDraft((p) => ({ ...p, title: e.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="story-summary">Summary</Label>
              <Textarea
                id="story-summary"
                rows={2}
                placeholder="One-sentence pitch of the story."
                value={draft.summary ?? ''}
                onChange={(e) => setDraft((p) => ({ ...p, summary: e.target.value }))}
              />
            </div>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
              <div className="space-y-2">
                <Label htmlFor="story-situation">Situation</Label>
                <Textarea
                  id="story-situation"
                  rows={3}
                  value={draft.situation ?? ''}
                  onChange={(e) => setDraft((p) => ({ ...p, situation: e.target.value }))}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="story-action">Action</Label>
                <Textarea
                  id="story-action"
                  rows={3}
                  value={draft.action ?? ''}
                  onChange={(e) => setDraft((p) => ({ ...p, action: e.target.value }))}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="story-result">Result</Label>
                <Textarea
                  id="story-result"
                  rows={3}
                  value={draft.result ?? ''}
                  onChange={(e) => setDraft((p) => ({ ...p, result: e.target.value }))}
                />
              </div>
            </div>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="story-metric">Impact Metric</Label>
                <Input
                  id="story-metric"
                  placeholder="e.g. 40% faster, $250k saved, 3x throughput"
                  value={draft.impact_metric ?? ''}
                  onChange={(e) => setDraft((p) => ({ ...p, impact_metric: e.target.value }))}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="story-role">Role Focus</Label>
                <Input
                  id="story-role"
                  placeholder="e.g. Backend, Platform, Staff Engineer"
                  value={draft.role_focus ?? ''}
                  onChange={(e) => setDraft((p) => ({ ...p, role_focus: e.target.value }))}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Tags</Label>
              <div className="flex gap-2">
                <Input
                  placeholder="e.g. leadership, migration, startup"
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      addTagToDraft();
                    }
                  }}
                />
                <Button variant="outline" size="sm" onClick={addTagToDraft} type="button">
                  Add
                </Button>
              </div>
              {(draft.tags ?? []).length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {(draft.tags ?? []).map((tag) => (
                    <Badge
                      key={tag}
                      variant="secondary"
                      className="cursor-pointer"
                      onClick={() => removeTagFromDraft(tag)}
                    >
                      {tag} &times;
                    </Badge>
                  ))}
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={cancel}>
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={save}
                disabled={createStory.isPending || updateStory.isPending}
              >
                {editingId ? 'Update Story' : 'Save Story'}
              </Button>
            </div>
          </div>
        )}

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading stories...</p>
        ) : stories.length === 0 && !showForm ? (
          <p className="text-sm text-muted-foreground">
            No stories yet. Add a few proof points and the AI will pull from them when drafting messages.
          </p>
        ) : (
          <div className="space-y-3">
            {stories.map((story) => (
              <div key={story.id} className="rounded-lg border p-3 space-y-2">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-medium">{story.title}</div>
                    {story.role_focus && (
                      <div className="text-xs text-muted-foreground">{story.role_focus}</div>
                    )}
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <Button variant="outline" size="sm" onClick={() => startEdit(story)}>
                      Edit
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => remove(story.id)}
                      disabled={deleteStory.isPending}
                    >
                      Delete
                    </Button>
                  </div>
                </div>
                {story.summary && <p className="text-sm">{story.summary}</p>}
                {story.impact_metric && (
                  <div className="text-xs text-muted-foreground">
                    Impact: {story.impact_metric}
                  </div>
                )}
                {story.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {story.tags.map((tag) => (
                      <Badge key={tag} variant="outline" className="text-xs">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
