import { useState, useEffect } from 'react';
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
import { toast } from 'sonner';
import type { Profile } from '@/types';

const GOALS = ['job', 'mentor', 'network'] as const;
const TONES = ['formal', 'conversational', 'humble'] as const;
const STEPS = ['Basics', 'Goals & Targets', 'Resume', 'Links'] as const;

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
  const [form, setForm] = useState<FormData>(profileToForm(undefined));
  const [tagInput, setTagInput] = useState({ industries: '', roles: '', locations: '', sizes: '' });

  useEffect(() => {
    if (profile) setForm(profileToForm(profile));
  }, [profile]);

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
