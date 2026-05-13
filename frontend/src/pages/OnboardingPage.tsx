import { useState, useRef, type FormEvent, type DragEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { useProfile, useUpdateProfile, useUploadResume } from '@/hooks/useProfile';
import { useSeedDefaultJobs } from '@/hooks/useJobs';
import { useCompleteOnboarding } from '@/hooks/useOnboarding';
import { toast } from 'sonner';
import {
  ArrowRight,
  Briefcase,
  CheckCircle2,
  FileText,
  Linkedin,
  Loader2,
  Rocket,
  Search,
  Upload,
  User,
} from 'lucide-react';

type Step = 'welcome' | 'profile' | 'resume' | 'linkedin' | 'discover' | 'done';

const STEPS: Step[] = ['welcome', 'profile', 'resume', 'linkedin', 'discover', 'done'];

function stepIndex(step: Step): number {
  return STEPS.indexOf(step);
}

function stepProgress(step: Step): number {
  return Math.round((stepIndex(step) / (STEPS.length - 1)) * 100);
}

const STEP_META: Record<Step, { icon: typeof Rocket; label: string }> = {
  welcome: { icon: Rocket, label: 'Welcome' },
  profile: { icon: User, label: 'Profile' },
  resume: { icon: FileText, label: 'Resume' },
  linkedin: { icon: Linkedin, label: 'LinkedIn' },
  discover: { icon: Search, label: 'Jobs' },
  done: { icon: CheckCircle2, label: 'Done' },
};

export function OnboardingPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>('welcome');
  const { data: profile } = useProfile();
  const updateProfile = useUpdateProfile();
  const uploadResume = useUploadResume();
  const seedJobs = useSeedDefaultJobs();
  const completeOnboarding = useCompleteOnboarding();

  // Profile step state
  const [fullName, setFullName] = useState('');
  const [targetRoles, setTargetRoles] = useState('');
  const [targetLocations, setTargetLocations] = useState('');

  // Resume step state
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // LinkedIn step state
  const [linkedinUrl, setLinkedinUrl] = useState('');

  // Discover step state
  const [jobsDiscovered, setJobsDiscovered] = useState(false);

  // Initialize fields from existing profile when it loads
  useState(() => {
    if (profile) {
      if (profile.full_name) setFullName(profile.full_name);
      if (profile.target_roles?.length) setTargetRoles(profile.target_roles.join(', '));
      if (profile.target_locations?.length) setTargetLocations(profile.target_locations.join(', '));
      if (profile.linkedin_url) setLinkedinUrl(profile.linkedin_url);
    }
  });

  const handleProfileSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const roles = targetRoles
      .split(',')
      .map((r) => r.trim())
      .filter(Boolean);
    const locations = targetLocations
      .split(',')
      .map((l) => l.trim())
      .filter(Boolean);

    try {
      await updateProfile.mutateAsync({
        full_name: fullName.trim(),
        target_roles: roles,
        target_locations: locations,
      });
      setStep('resume');
    } catch {
      toast.error('Failed to save profile');
    }
  };

  const handleFileSelect = (file: File) => {
    const validTypes = [
      'application/pdf',
      'application/msword',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    ];
    if (!validTypes.includes(file.type)) {
      toast.error('Please upload a PDF or Word document');
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      toast.error('File must be under 10 MB');
      return;
    }
    setResumeFile(file);
  };

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFileSelect(file);
  };

  const handleResumeUpload = async () => {
    if (!resumeFile) {
      setStep('linkedin');
      return;
    }
    try {
      await uploadResume.mutateAsync(resumeFile);
      toast.success('Resume uploaded and parsed');
      setStep('linkedin');
    } catch {
      toast.error('Failed to upload resume');
    }
  };

  const handleLinkedinSubmit = async () => {
    if (linkedinUrl.trim()) {
      try {
        await updateProfile.mutateAsync({ linkedin_url: linkedinUrl.trim() });
      } catch {
        toast.error('Failed to save LinkedIn URL');
      }
    }
    setStep('discover');
  };

  const handleDiscoverJobs = async () => {
    try {
      const result = await seedJobs.mutateAsync();
      setJobsDiscovered(true);
      toast.success(`Found ${result.new_jobs_found} jobs for you`);
    } catch {
      toast.error('Failed to discover jobs');
    }
  };

  const handleComplete = async () => {
    try {
      await completeOnboarding.mutateAsync();
      navigate('/dashboard', { replace: true });
    } catch {
      // Even if the API call fails, send them to dashboard
      navigate('/dashboard', { replace: true });
    }
  };

  const progressValue = stepProgress(step);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* Header */}
      <header className="border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-2xl items-center justify-between px-4">
          <span className="text-xl font-bold tracking-tight">NexusReach</span>
          {step !== 'welcome' && step !== 'done' && (
            <span className="text-sm text-muted-foreground">
              Step {stepIndex(step)} of {STEPS.length - 2}
            </span>
          )}
        </div>
      </header>

      {/* Progress bar */}
      {step !== 'welcome' && (
        <div className="mx-auto w-full max-w-2xl px-4 pt-4">
          <Progress value={progressValue} className="h-1.5" />
          <div className="mt-2 flex justify-between">
            {STEPS.filter((s) => s !== 'welcome').map((s) => {
              const meta = STEP_META[s];
              const Icon = meta.icon;
              const isActive = s === step;
              const isPast = stepIndex(s) < stepIndex(step);
              return (
                <div
                  key={s}
                  className={`flex flex-col items-center gap-1 ${
                    isActive
                      ? 'text-primary'
                      : isPast
                        ? 'text-primary/60'
                        : 'text-muted-foreground/40'
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  <span className="text-[10px] font-medium hidden sm:block">{meta.label}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Step content */}
      <main className="flex flex-1 items-center justify-center px-4 py-8">
        <Card className="w-full max-w-lg">
          <CardContent className="p-6 sm:p-8">
            {/* Welcome */}
            {step === 'welcome' && (
              <div className="flex flex-col items-center gap-6 text-center">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
                  <Rocket className="h-8 w-8 text-primary" />
                </div>
                <div className="space-y-2">
                  <h1 className="text-2xl font-bold tracking-tight">
                    Welcome to NexusReach
                  </h1>
                  <p className="text-muted-foreground">
                    Let's get you set up in a few quick steps so we can start
                    finding the right opportunities for you.
                  </p>
                </div>
                <div className="w-full space-y-3 text-left">
                  {[
                    { icon: User, text: 'Set up your profile and target roles' },
                    { icon: FileText, text: 'Import your resume for better matching' },
                    { icon: Search, text: 'Discover your first batch of jobs' },
                  ].map(({ icon: Icon, text }) => (
                    <div key={text} className="flex items-center gap-3 rounded-lg border p-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted">
                        <Icon className="h-4 w-4 text-muted-foreground" />
                      </div>
                      <span className="text-sm">{text}</span>
                    </div>
                  ))}
                </div>
                <Button onClick={() => setStep('profile')} className="w-full" size="lg">
                  Get started <ArrowRight className="ml-1 h-4 w-4" />
                </Button>
              </div>
            )}

            {/* Profile */}
            {step === 'profile' && (
              <div className="space-y-6">
                <div className="space-y-2 text-center">
                  <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                    <User className="h-6 w-6 text-primary" />
                  </div>
                  <h2 className="text-xl font-bold">Tell us about yourself</h2>
                  <p className="text-sm text-muted-foreground">
                    This helps us find the right jobs and personalize your outreach.
                  </p>
                </div>
                <form onSubmit={handleProfileSubmit} className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="ob-fullname">Full name</Label>
                    <Input
                      id="ob-fullname"
                      placeholder="Jane Doe"
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      autoFocus
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="ob-roles">Target roles</Label>
                    <Input
                      id="ob-roles"
                      placeholder="Software Engineer, Frontend Developer"
                      value={targetRoles}
                      onChange={(e) => setTargetRoles(e.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Separate multiple roles with commas
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="ob-locations">Target locations</Label>
                    <Input
                      id="ob-locations"
                      placeholder="San Francisco, Remote, New York"
                      value={targetLocations}
                      onChange={(e) => setTargetLocations(e.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Separate multiple locations with commas
                    </p>
                  </div>
                  <div className="flex gap-2 pt-2">
                    <Button
                      type="button"
                      variant="outline"
                      className="flex-1"
                      onClick={() => setStep('resume')}
                    >
                      Skip for now
                    </Button>
                    <Button type="submit" className="flex-1" disabled={updateProfile.isPending}>
                      {updateProfile.isPending ? (
                        <>
                          <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                          Saving...
                        </>
                      ) : (
                        <>
                          Continue <ArrowRight className="ml-1 h-4 w-4" />
                        </>
                      )}
                    </Button>
                  </div>
                </form>
              </div>
            )}

            {/* Resume */}
            {step === 'resume' && (
              <div className="space-y-6">
                <div className="space-y-2 text-center">
                  <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                    <FileText className="h-6 w-6 text-primary" />
                  </div>
                  <h2 className="text-xl font-bold">Upload your resume</h2>
                  <p className="text-sm text-muted-foreground">
                    We'll parse your experience to improve job matching and message drafting.
                  </p>
                </div>

                <div
                  className={`relative flex flex-col items-center gap-3 rounded-lg border-2 border-dashed p-8 transition-colors ${
                    isDragging
                      ? 'border-primary bg-primary/5'
                      : resumeFile
                        ? 'border-green-500/50 bg-green-50 dark:bg-green-900/10'
                        : 'border-muted-foreground/25 hover:border-muted-foreground/50'
                  }`}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                >
                  {resumeFile ? (
                    <>
                      <CheckCircle2 className="h-8 w-8 text-green-600 dark:text-green-400" />
                      <div className="text-center">
                        <p className="font-medium">{resumeFile.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {(resumeFile.size / 1024).toFixed(0)} KB
                        </p>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setResumeFile(null);
                          if (fileInputRef.current) fileInputRef.current.value = '';
                        }}
                      >
                        Remove
                      </Button>
                    </>
                  ) : (
                    <>
                      <Upload className="h-8 w-8 text-muted-foreground" />
                      <div className="text-center">
                        <p className="font-medium">
                          Drag and drop your resume here
                        </p>
                        <p className="text-xs text-muted-foreground">
                          PDF or Word, up to 10 MB
                        </p>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => fileInputRef.current?.click()}
                      >
                        Browse files
                      </Button>
                    </>
                  )}
                  <input
                    ref={fileInputRef}
                    type="file"
                    className="hidden"
                    accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) handleFileSelect(file);
                    }}
                  />
                </div>

                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    className="flex-1"
                    onClick={() => setStep('linkedin')}
                  >
                    Skip for now
                  </Button>
                  <Button
                    className="flex-1"
                    onClick={handleResumeUpload}
                    disabled={uploadResume.isPending}
                  >
                    {uploadResume.isPending ? (
                      <>
                        <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                        Uploading...
                      </>
                    ) : resumeFile ? (
                      <>
                        Upload & Continue <ArrowRight className="ml-1 h-4 w-4" />
                      </>
                    ) : (
                      <>
                        Continue <ArrowRight className="ml-1 h-4 w-4" />
                      </>
                    )}
                  </Button>
                </div>
              </div>
            )}

            {/* LinkedIn */}
            {step === 'linkedin' && (
              <div className="space-y-6">
                <div className="space-y-2 text-center">
                  <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                    <Linkedin className="h-6 w-6 text-primary" />
                  </div>
                  <h2 className="text-xl font-bold">Link your LinkedIn</h2>
                  <p className="text-sm text-muted-foreground">
                    Adding your profile URL helps us find warm paths and personalize outreach.
                    You can also import your connections later in Settings.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="ob-linkedin">LinkedIn profile URL</Label>
                  <Input
                    id="ob-linkedin"
                    placeholder="https://linkedin.com/in/janedoe"
                    value={linkedinUrl}
                    onChange={(e) => setLinkedinUrl(e.target.value)}
                    autoFocus
                  />
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    className="flex-1"
                    onClick={() => {
                      setLinkedinUrl('');
                      setStep('discover');
                    }}
                  >
                    Skip for now
                  </Button>
                  <Button
                    className="flex-1"
                    onClick={handleLinkedinSubmit}
                    disabled={updateProfile.isPending}
                  >
                    {updateProfile.isPending ? (
                      <>
                        <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                        Saving...
                      </>
                    ) : (
                      <>
                        Continue <ArrowRight className="ml-1 h-4 w-4" />
                      </>
                    )}
                  </Button>
                </div>
              </div>
            )}

            {/* Discover Jobs */}
            {step === 'discover' && (
              <div className="space-y-6">
                <div className="space-y-2 text-center">
                  <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                    <Briefcase className="h-6 w-6 text-primary" />
                  </div>
                  <h2 className="text-xl font-bold">Discover your first jobs</h2>
                  <p className="text-sm text-muted-foreground">
                    {jobsDiscovered
                      ? 'Great! We found jobs matching your profile. You can explore them on your dashboard.'
                      : 'We\'ll search across dozens of job boards to find roles that match your profile.'}
                  </p>
                </div>

                {!jobsDiscovered ? (
                  <div className="space-y-4">
                    <div className="rounded-lg border bg-muted/30 p-4">
                      <div className="flex items-start gap-3">
                        <Search className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
                        <div className="text-sm text-muted-foreground">
                          <p>This will search across multiple sources including:</p>
                          <ul className="mt-2 list-inside list-disc space-y-1">
                            <li>Major job boards (LinkedIn, Indeed, Glassdoor)</li>
                            <li>Company career pages and ATS platforms</li>
                            <li>Startup-focused boards (YC, Wellfound)</li>
                          </ul>
                        </div>
                      </div>
                    </div>
                    <Button
                      className="w-full"
                      size="lg"
                      onClick={handleDiscoverJobs}
                      disabled={seedJobs.isPending}
                    >
                      {seedJobs.isPending ? (
                        <>
                          <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                          Discovering jobs...
                        </>
                      ) : (
                        <>
                          <Search className="mr-1 h-4 w-4" />
                          Discover jobs
                        </>
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      className="w-full"
                      onClick={() => setStep('done')}
                    >
                      Skip — I'll browse jobs later
                    </Button>
                  </div>
                ) : (
                  <Button
                    className="w-full"
                    size="lg"
                    onClick={() => setStep('done')}
                  >
                    Continue <ArrowRight className="ml-1 h-4 w-4" />
                  </Button>
                )}
              </div>
            )}

            {/* Done */}
            {step === 'done' && (
              <div className="flex flex-col items-center gap-6 text-center">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/20">
                  <CheckCircle2 className="h-8 w-8 text-green-600 dark:text-green-400" />
                </div>
                <div className="space-y-2">
                  <h2 className="text-2xl font-bold">You're all set!</h2>
                  <p className="text-muted-foreground">
                    Your account is ready. Here's what you can do next:
                  </p>
                </div>
                <div className="w-full space-y-2 text-left">
                  {[
                    { icon: Briefcase, text: 'Browse and apply to jobs on your feed' },
                    { icon: User, text: 'Find contacts and hiring managers at target companies' },
                    { icon: FileText, text: 'Complete your full profile for better matches' },
                  ].map(({ icon: Icon, text }) => (
                    <div key={text} className="flex items-center gap-3 rounded-lg border p-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted">
                        <Icon className="h-4 w-4 text-muted-foreground" />
                      </div>
                      <span className="text-sm">{text}</span>
                    </div>
                  ))}
                </div>
                <Button
                  onClick={handleComplete}
                  className="w-full"
                  size="lg"
                  disabled={completeOnboarding.isPending}
                >
                  {completeOnboarding.isPending ? (
                    <>
                      <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                      Finishing up...
                    </>
                  ) : (
                    'Go to Dashboard'
                  )}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}

export default OnboardingPage;
