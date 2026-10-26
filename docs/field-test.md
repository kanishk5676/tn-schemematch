# Field test: five tasks with real people

The app has been tested by code and by a browser at phone width. It has not been tested by
the people it is for. This is how to do that honestly, in an afternoon, with 5 to 10 people:
family, neighbours, a village, or the people waiting at an e-Sevai centre.

## Before you go

- **Run guided mode** (`python scripts/serve.py --backend none`) unless you have a key and a
  budget — it is the version that always works. Note which one you used.
- **Use a cheap Android phone in Chrome**, the kind people own. Check it has a Tamil voice:
  Settings → Text-to-speech → Google → install Tamil. Note if it did not.
- **Set a helper PIN** and save each person under a code (P1, P2…), never their real name
  in your notes. Delete the vault when you are done (`rm -rf data/vault`).
- **Ask for consent** in Tamil, out loud: what the test is, that it is about the app not
  about them, that they can stop at any time, and that nothing they say leaves the phone
  except the speech, which Chrome sends to Google. Note who agreed.
- **Bring a helper who knows the schemes** (an e-Sevai operator, a VAO's assistant, a
  social worker) to check whether the schemes the app finds are right.

## The five tasks

Say each task in Tamil, then do not help unless they are stuck for a full minute. If you
help, write down exactly what you said.

| # | Task (say it like this) | Done when |
|---|---|---|
| 1 | "உங்களுக்கு என்ன அரசுத் திட்டம் கிடைக்கும் என்று இதில் கண்டுபிடியுங்கள்." *Find what schemes you can get.* | The result screen shows, or they say they are finished. |
| 2 | "அதற்கு என்ன ஆவணங்கள் கொண்டு போக வேண்டும் என்று சொல்லுங்கள்." *Tell me which documents you need.* | They say at least one document from the list. |
| 3 | "உங்கள் விவரங்களைச் சேமியுங்கள்." *Save your details.* | A profile is saved. |
| 4 | "ஒரு ஆவணத்தின் படத்தை அனுப்புங்கள்." *Upload a photo of a document* (a ration card is fine; cover the numbers). | The document appears on the profile. |
| 5 | "எங்கே போக வேண்டும் என்று கேட்டுச் சொல்லுங்கள்." *Hear where to go, and tell me.* | They repeat the office, from what they heard. |

## What to write down, for each person

Use one row per person. Do not round, do not tidy.

| Field | |
|---|---|
| Code | P1, P2, … |
| Language they used | Tamil / Tanglish / English / mixed |
| Could read the screen? | yes / some / no |
| Used the microphone? | yes / tried, failed / no |
| Task 1 done? time? help needed? | |
| Task 2 done? time? help needed? | |
| Task 3 done? time? help needed? | |
| Task 4 done? time? help needed? | |
| Task 5 done? time? help needed? | |
| What confused them (their words) | |
| Schemes found | |
| Helper's check: right? missing? wrong? | For every scheme the app said, and any it missed. |
| Anything they said they would do next | |

## After

1. **Count, don't summarise:** how many finished each task, the median time, how many
   needed help, how many used the microphone, how many schemes the helper marked wrong.
2. **Every wrong "yes"** the helper found is a bug in a rule. Open the scheme file, check it
   against the source, fix it, and run `python scripts/gold_diff.py` to see who else it moves.
3. **Every wrong "no"** is either a rule or a question the person could not answer — find
   which.
4. **Fix the top three problems** people hit, then test again with two new people.
5. Put the numbers in the README, including the bad ones.
